"""Explicit artificial observations for SDK orchestration tests, never scores.

This module does not import task parsers, fitting code or a candidate runner.
Metadata hashes describe the target interface only. Values below are invented
fixtures and must never be relabelled observed or counted in a research ledger.
"""
import json
from pathlib import Path

from . import strategy_binding as binding
from .role_executor import LIMITS, runtime_inventory
from .strategy_pair_controller import write_once
from .strategy_partition import safe_path


class SyntheticExecutorFactory:
    synthetic_only=True

    def __init__(self, output):
        self.output=output
        self.calls=0
        self._runtime=None

    def __call__(self, root, *, role, evaluation_gate=None):
        if evaluation_gate is not None or role not in ('learning','selection','evaluation'):
            raise ValueError('Simulation cannot accept production gate or unknown role')
        root=Path(root)
        safe_path(root,self.output)
        partition=json.loads((root/binding.PARTITION).read_bytes())
        if self._runtime is None:
            self._runtime=runtime_inventory()
        factory=self

        class SyntheticExecutor:
            synthetic_only=True

            def evaluate(self,family,task_id,source,*,n_params=0,candidate_id=None,parent_id=None,strategy_version='baseline'):
                if family not in ('planning','symbolic'):
                    raise ValueError('Unknown synthetic family')
                entries=partition['planning']['tasks'] if family=='planning' else partition['symbolic']['files']
                found=[x for x in entries if x['task_id']==task_id and x['role']==role
                       and (family=='planning' or x['split']=='train')]
                if len(found)!=1:
                    raise ValueError('Synthetic task role mismatch')
                if type(source) is not str or type(n_params) is not int or not 0<=n_params<=16:
                    raise ValueError('Synthetic source contract')
                entry=found[0]
                factory.calls+=1
                directory=safe_path(root,factory.output+'/synthetic-observations/'+str(factory.calls).zfill(4))
                directory.mkdir(parents=True,exist_ok=False)
                write_once(directory/'source.py',source.encode(),raw=True)
                source_ref=binding.file_ref(root,(directory/'source.py').relative_to(root).as_posix())
                files,runtime=factory._runtime
                request=dict(version='role-executor-v0.1',role=role,family=family,task_id=task_id,
                    candidate_sha256=source_ref['sha256'],n_params=n_params,strategy_version=strategy_version,
                    partition_sha256=binding.PARTITION_SHA256,data_sha256=entry['sha256'],
                    domain_sha256=partition['planning']['domain_sha256'] if family=='planning' else None,
                    evaluator_sha256=runtime,metric_scope=role if family=='planning' else 'train',limits=LIMITS)
                write_once(directory/'request.json',request)
                request_ref=binding.file_ref(root,(directory/'request.json').relative_to(root).as_posix())
                row={k:v for k,v in request.items() if k not in ('role','candidate_sha256')}
                row.update(record_kind='executor_observation',evidence_kind='synthetic',synthetic_observation_only=True,
                    task_role=role,candidate_hash=source_ref['sha256'],runtime_files=files,model_calls=0,sealed_tasks_executed=0,
                    request_sha256=request_ref['sha256'],journal_path=(directory/'result.json').relative_to(root).as_posix(),
                    candidate_id=candidate_id,parent_id=parent_id,status='success',
                    executions=[dict(phase='plan',status='completed',synthetic=True)])
                if family=='planning':
                    row['validator']=dict(status='valid',synthetic=True)
                else:
                    row.update(metrics=dict(nmse=0.1,mse=0.2),
                        fitting=dict(n_params=n_params,split='train',converged=True,params=[0.0]*n_params,
                                     nfev=1,candidate_calls=1,max_nfev=100),
                        executions=[dict(phase=p,status='completed',synthetic=True) for p in ('fit','predict')])
                write_once(directory/'result.json',row)
                return row

        return SyntheticExecutor()


class SyntheticProvider:
    """One deterministic provider reply per frozen slot, used only under patch."""
    def __init__(self, slots):
        self.slots=slots
        self.calls=0

    def __call__(self,**kwargs):
        from litellm.types.utils import ModelResponse
        if self.calls>=len(self.slots):
            raise RuntimeError('Synthetic provider exceeded frozen slots')
        slot=self.slots[self.calls]
        self.calls+=1
        users=[m for m in kwargs['messages'] if m['role']=='user']
        if len(users)!=1:
            raise ValueError('Synthetic provider expects one packet')
        content=users[0]['content']
        if isinstance(content,list):
            content=content[0]['text']
        packet=json.loads(content)
        if slot['phase']=='update':
            tool='submit_policy'
            rules=['R05' if slot['arm']=='shadow' else ('R01' if slot['replicate']=='r1' else 'R02'),'R04','R06','R08']
            arguments={f'rule_{i}':value for i,value in enumerate(rules,1)}
        else:
            tool='submit_candidate'
            state=packet['current_state']
            arguments=dict(source=state['source'],n_params=state['n_params'])
        return ModelResponse(id=f'synthetic-response-{self.calls:04d}',model='minimax-m3',
            choices=[dict(message=dict(role='assistant',content='Artificial integration fixture; no research result.',
                tool_calls=[dict(id=f'synthetic-call-{self.calls:04d}',type='function',
                    function=dict(name=tool,arguments=json.dumps(arguments)))]),finish_reason='tool_calls')],
            usage=dict(prompt_tokens=100,completion_tokens=20,total_tokens=120))
