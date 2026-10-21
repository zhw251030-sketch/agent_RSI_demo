Produce one complete Python planning program from the public contract and two example inputs. There is no starting program, measured feedback, reference plan or opportunity for a second submission. Aim to solve the task; do not intentionally insert defects. Your source will be stored without being run. Do not claim it has passed any task.

Define `get_plan(objects, init, goal)`. At execution, objects is a set of (object_name, declared_type) tuples; init and goal are sets of predicate tuples. The JSON examples use arrays in place of sets and tuples. Return a list of at most 1000 grounded action strings, each one parenthesized, using the exact argument order below. Do not hardcode example objects or a plan. Do not mutate the inputs or rely on set iteration order.

This is the public domain definition, not a solution. A missing fact is false. Links are directed, and action preconditions must hold after preceding effects.

```lisp
(define (domain spanner)
(:requirements :typing :strips)
(:types location locatable - object man nut spanner - locatable)
(:predicates
  (at ?m - locatable ?l - location)
  (carrying ?m - man ?s - spanner)
  (useable ?s - spanner)
  (link ?l1 - location ?l2 - location)
  (tightened ?n - nut)
  (loose ?n - nut))
(:action walk
  :parameters (?start - location ?end - location ?m - man)
  :precondition (and (at ?m ?start) (link ?start ?end))
  :effect (and (not (at ?m ?start)) (at ?m ?end)))
(:action pickup_spanner
  :parameters (?l - location ?s - spanner ?m - man)
  :precondition (and (at ?m ?l) (at ?s ?l))
  :effect (and (not (at ?s ?l)) (carrying ?m ?s)))
(:action tighten_nut
  :parameters (?l - location ?s - spanner ?m - man ?n - nut)
  :precondition (and (at ?m ?l) (at ?n ?l) (carrying ?m ?s) (useable ?s) (loose ?n))
  :effect (and (not (loose ?n)) (not (useable ?s)) (tightened ?n)))
)
```

Use only Python's standard library. Do not access files, network, subprocesses or other programs. Submit the complete source once with n_params=0 through submit_candidate. Only source and n_params are accepted; do not include explanations or additional fields.
