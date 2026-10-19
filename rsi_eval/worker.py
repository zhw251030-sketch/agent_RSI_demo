"""Trusted bootstrap loaded inside bubblewrap, never an in-process host fallback."""
from __future__ import annotations

import contextlib
import ctypes
import errno
import importlib
import json
import os
from pathlib import Path
import resource
import sys


class ArgComparison(ctypes.Structure):
    _fields_ = [("arg", ctypes.c_uint32), ("op", ctypes.c_uint32),
                ("datum_a", ctypes.c_uint64), ("datum_b", ctypes.c_uint64)]


def restrict_syscalls():
    """Deny process/network creation and filesystem mutation after imports."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise OSError(ctypes.get_errno(), "no_new_privs failed")
    library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                              ctypes.c_int, ctypes.c_uint,
                                              ctypes.POINTER(ArgComparison)]
    context = library.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("seccomp initialization failed")

    def deny(name, comparison=None):
        syscall = library.seccomp_syscall_resolve_name(name.encode("ascii"))
        if syscall < 0:  # syscall does not exist on this architecture
            return
        array = None if comparison is None else ctypes.pointer(comparison)
        result = library.seccomp_rule_add_array(context, 0x00050000 | errno.EPERM,
                                                syscall, int(comparison is not None), array)
        if result != 0:
            raise RuntimeError(f"seccomp rule failed: {name} ({result})")

    try:
        names = """fork vfork clone clone3 execve execveat ptrace process_vm_readv process_vm_writev
        mount umount2 pivot_root chroot unshare setns bpf perf_event_open keyctl add_key request_key
        socket socketpair connect bind listen accept accept4 sendto sendmsg sendmmsg
        creat openat2 truncate ftruncate fallocate mkdir mkdirat rmdir unlink unlinkat rename renameat
        renameat2 link linkat symlink symlinkat chmod fchmod fchmodat chown fchown lchown fchownat
        mknod mknodat utime utimes utimensat futimesat setxattr lsetxattr fsetxattr removexattr
        lremovexattr fremovexattr memfd_create io_uring_setup userfaultfd reboot swapon swapoff
        init_module finit_module delete_module kexec_load kexec_file_load quotactl""".split()
        for name in names:
            deny(name)
        write_flags = [os.O_CREAT, os.O_TRUNC, os.O_APPEND]
        if hasattr(os, "O_TMPFILE"):
            write_flags.append(os.O_TMPFILE & ~os.O_DIRECTORY)
        for name, argument in (("open", 1), ("openat", 2)):
            for access in (os.O_WRONLY, os.O_RDWR):
                deny(name, ArgComparison(argument, 7, os.O_ACCMODE, access))  # MASKED_EQ
            for flag in write_flags:
                deny(name, ArgComparison(argument, 7, flag, flag))
        if library.seccomp_load(context) != 0:
            raise RuntimeError("seccomp filter load failed")
    finally:
        library.seccomp_release(context)


def main():
    try:
        memory_mb, cpu_seconds = map(int, sys.argv[1:3])
        resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024**2,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        sys.path.insert(0, "/runtime")
        if Path("/deps").is_dir():
            sys.path.insert(0, "/deps")
        request = json.loads(Path("/work/request.json").read_text(encoding="utf-8"))
        source = Path("/work/candidate.py").read_text(encoding="utf-8")
        family = request["family"]
        if family not in {"planning", "symbolic"}:
            raise ValueError("unknown family")
        module = importlib.import_module(f"rsi_eval.{family}_worker")
        module.prepare_runtime()
        restrict_syscalls()
    except BaseException as exc:
        print(f"worker bootstrap failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 70
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = module.run(source, request)
    except MemoryError:
        result = {"status": "resource_limit", "error_type": "MemoryError"}
    except BaseException as exc:
        result = {"status": "candidate_error", "error_type": type(exc).__name__,
                  "message": str(exc)[:1000]}
    try:
        print(json.dumps(result, allow_nan=False, separators=(",", ":")), flush=True)
    except (ValueError, TypeError) as exc:
        print(json.dumps({"status": "candidate_error", "error_type": type(exc).__name__,
                          "message": "worker result is not finite JSON"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
