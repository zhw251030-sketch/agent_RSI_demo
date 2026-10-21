(define (problem small) (:domain spanner)
 (:objects bob - man nut1 - nut shed gate - location)
 (:init (at bob shed) (at nut1 gate) (link shed gate))
 (:goal (and (at bob gate))))