"""Exact bounded factor splits and construction estimates for prime powers."""
from functools import lru_cache
from recipe_graph_optimizer import Recipe

PRIMES = (2,3,5,7,11,13,17,19,23,29,31,37,41,43,47,53,59,61,67,71,73,79,83,89,97)


@lru_cache(maxsize=200000)
def small_factors(value):
    factors=[]
    for prime in PRIMES:
        if prime*prime>value:
            break
        exponent=0
        while value%prime==0:
            value//=prime
            exponent+=1
        if exponent:
            factors.append((prime,exponent))
    if value>1:
        # The residual need not be prime; all proposed products remain exact.
        factors.append((value,1))
    return tuple(factors)


def construction_estimate(value, initial, one_step, weight):
    factors=small_factors(value)
    cost=max(0,len(factors)-1)
    for prime,exponent in factors:
        if prime in initial:
            base=0
        elif prime in one_step:
            base=1
        else:
            base=weight*prime.bit_length()
        cost+=base+exponent.bit_length()-1+exponent.bit_count()-1
    return cost


def factor_patches(puzzle, value, graph):
    for delta in (0,1,-1,2,-2):
        product=value+delta
        if not 1<product<=puzzle.value_limit or abs(delta)>=value:
            continue
        if delta and product in graph:
            continue
        factors=small_factors(product)
        divisors=set()
        balanced=1
        for prime,exponent in sorted(factors,key=lambda x:-(x[0]**x[1]).bit_length()):
            for power in {1,exponent//2,exponent} - {0}:
                divisors.add(prime**power)
            if balanced*balanced<product:
                balanced*=prime**exponent
                divisors.add(balanced)
        for a in sorted(divisors):
            b=product//a
            if not 1<a<value or not 1<b<value:
                continue
            patch={product:Recipe('*',a,b)}
            if delta:
                patch[value]=Recipe('-' if delta>0 else '+',product,abs(delta))
            yield patch
