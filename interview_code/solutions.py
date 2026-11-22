"""Verified solutions to the coding questions reported from real interviews.  Run: python solutions.py"""
import asyncio
import copy
import functools
import io
import math
import re
import time
from collections import Counter, defaultdict

import pandas as pd

# 1) A={1..5}, B={6..10} -> {6,14,24,36,50}  (pairwise product; sets are unordered so SORT first)
def pairwise_product(a, b):
    return {x * y for x, y in zip(sorted(a), sorted(b))}
assert pairwise_product({1, 2, 3, 4, 5}, {6, 7, 8, 9, 10}) == {6, 14, 24, 36, 50}


# 2) merge two SORTED lists (two pointers, O(n+m))
def merge_sorted(l1, l2):
    i = j = 0
    out = []
    while i < len(l1) and j < len(l2):
        if l1[i] <= l2[j]:
            out.append(l1[i]); i += 1
        else:
            out.append(l2[j]); j += 1
    out.extend(l1[i:]); out.extend(l2[j:])
    return out
assert merge_sorted([-1, 1, 3, 4], [-3, -2, 4]) == [-3, -2, -1, 1, 3, 4, 4]
assert merge_sorted([-1, 1, 3, 4], sorted([-2, -3, 4])) == [-3, -2, -1, 1, 3, 4, 4]   # interview l2 was NOT sorted


# 3) second largest, single pass, duplicates-safe
def second_largest(nums):
    first = second = float("-inf")
    for n in nums:
        if n > first:
            first, second = n, first
        elif first > n > second:
            second = n
    return second
assert second_largest([-2, -10, 0, 6, 1, 5]) == 5 and second_largest([1, 10, 3, 4, 5, 6, 7, 8, 10, 9]) == 9

# 4) sort dict by value descending
d = {"index1": 12, "index2": 5, "index3": 10}
assert sorted(d.items(), key=lambda kv: kv[1], reverse=True) == [("index1", 12), ("index3", 10), ("index2", 5)]
assert dict(sorted(d.items(), key=lambda kv: -kv[1])) == {"index1": 12, "index3": 10, "index2": 5}


# 5) flatten "{1,{2,{3,4},5},6}" -> [1,2,3,4,5,6]
def flatten_str(s):
    return [int(x) for x in re.findall(r"-?\d+", s)]


def flatten_nested(x):
    for item in x:
        if isinstance(item, (list, tuple, set)):
            yield from flatten_nested(item)
        else:
            yield item


def parse_nested(s):
    stack, cur, num = [], [], ""
    for ch in s:
        if ch.isdigit() or ch == "-":
            num += ch
        else:
            if num:
                cur.append(int(num)); num = ""
            if ch == "{":
                stack.append(cur); cur = []
            elif ch == "}":
                inner, cur = cur, stack.pop(); cur.append(inner)
    return cur[0] if cur and isinstance(cur[0], list) else cur
assert flatten_str("{1,{2,{3,4},5},6}") == [1, 2, 3, 4, 5, 6]
assert list(flatten_nested([1, [2, [3, 4], 5], 6])) == [1, 2, 3, 4, 5, 6]
assert parse_nested("{1,{2,{3,4},5},6}") == [1, [2, [3, 4], 5], 6]


# 6) longest substring without repeating chars (sliding window, O(n))
def longest_unique_substring(s):
    last, start, best = {}, 0, (0, 0)
    for i, ch in enumerate(s):
        if ch in last and last[ch] >= start:
            start = last[ch] + 1
        last[ch] = i
        if i - start + 1 > best[1] - best[0]:
            best = (start, i + 1)
    return s[best[0]:best[1]]
assert longest_unique_substring("abcwdbcbb") == "abcwd"     # the interview comment said "abc": that is WRONG
assert longest_unique_substring("") == "" and longest_unique_substring("bbbb") == "b"


# 7) first non-repeated character
def first_unique(s):
    counts = Counter(s)
    return next((c for c in s if counts[c] == 1), None)
assert first_unique("Nikhil") == "N" and first_unique("aabb") is None


# 8) primes
def primes_upto(n):
    return [k for k in range(2, n + 1) if all(k % i for i in range(2, math.isqrt(k) + 1))]


def sieve(n):
    flags = [True] * (n + 1)
    flags[:2] = [False, False]
    for i in range(2, math.isqrt(n) + 1):
        if flags[i]:
            flags[i * i::i] = [False] * len(flags[i * i::i])
    return [i for i, f in enumerate(flags) if f]


def primes_in_list(nums):
    return [n for n in nums if n > 1 and all(n % i for i in range(2, math.isqrt(n) + 1))]
assert primes_upto(100) == sieve(100) and len(sieve(100)) == 25
assert primes_in_list([1, 2, 3, 4, 5, 9, 11, 15, 17]) == [2, 3, 5, 11, 17]

# 9) the "growing groups" snippet
s, i, index, group, lines = "abcdefghijjkkj", 0, 1, 0, []
while i < len(s) and index <= 4:
    lines.append((s[i:i + index], group)); i += index; index += 1; group += 1
assert lines == [("a", 0), ("bc", 1), ("def", 2), ("ghij", 3)]


# 10) dict keys sorted then reversed
def reverse_key(dictt):
    return "".join(dict(sorted(dictt.items())).keys())[::-1]
assert reverse_key({"a": 1, "b": 2, "d": 56, "c": 3}) == "dcba"

# 11) pandas: DataFrame + null values
df = pd.read_csv(io.StringIO("id,name,age\n1,A,30\n2,,\n3,C,25\n"))
assert df.isnull().sum().to_dict() == {"id": 0, "name": 1, "age": 1}
assert (df.isnull().mean() * 100).round(1)["age"] == 33.3
assert df.dropna().shape == (2, 3) and df.fillna({"age": df["age"].median()}).loc[1, "age"] == 27.5


# 12) big file, small RAM: stream chunks, keep aggregates only
def count_nulls_streaming(buf, chunksize=2):
    totals = None
    for chunk in pd.read_csv(buf, chunksize=chunksize):
        n = chunk.isnull().sum()
        totals = n if totals is None else totals.add(n, fill_value=0)
    return totals.astype(int).to_dict()
assert count_nulls_streaming(io.StringIO("a,b\n1,\n,2\n3,4\n,\n")) == {"a": 2, "b": 2}


# 13) asyncio gather vs create_task
async def fetch(name, delay):
    await asyncio.sleep(delay)
    return name


async def demo():
    r = await asyncio.gather(fetch("a", .05), fetch("b", .05), fetch("c", .05))
    t1 = asyncio.create_task(fetch("x", .05)); t2 = asyncio.create_task(fetch("y", .05))
    return r, [await t1, await t2]
r, t = asyncio.run(demo())
assert r == ["a", "b", "c"] and t == ["x", "y"]


# 14) decorator, generator, rate-limit decorator
def timer(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        return fn(*a, **k)
    return wrapper


@timer
def work():
    return 42
assert work() == 42 and work.__name__ == "work"


def read_big(lines):
    for line in lines:
        yield line.strip()
g = read_big(["a\n", "b\n"])
assert next(g) == "a" and list(g) == ["b"]


def rate_limit(calls, per):
    stamps = []

    def deco(fn):
        @functools.wraps(fn)
        def inner(*a, **k):
            now = time.monotonic()
            stamps[:] = [t0 for t0 in stamps if now - t0 < per]
            if len(stamps) >= calls:
                raise RuntimeError("429 too many requests")
            stamps.append(now)
            return fn(*a, **k)
        return inner
    return deco


@rate_limit(2, 1.0)
def ping():
    return "ok"
ping(); ping()
try:
    ping()
    raise SystemExit("should have been limited")
except RuntimeError:
    pass

# 15) shallow vs deep copy
a = [[1, 2], [3]]
sh, dp = copy.copy(a), copy.deepcopy(a)
a[0].append(99)
assert sh[0] == [1, 2, 99] and dp[0] == [1, 2]


# 16) retrieval metrics + RRF
def precision_at_k(ret, rel, k): return sum(x in rel for x in ret[:k]) / k
def recall_at_k(ret, rel, k): return sum(x in rel for x in ret[:k]) / len(rel)
def hit_rate_at_k(ret, rel, k): return float(any(x in rel for x in ret[:k]))
def reciprocal_rank(ret, rel): return next((1 / (i + 1) for i, x in enumerate(ret) if x in rel), 0.0)


def ndcg_at_k(ret, rel, k):
    dcg = sum(1 / math.log2(i + 2) for i, x in enumerate(ret[:k]) if x in rel)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(rel), k)))
    return dcg / idcg


ret, rel = ["d1", "d9", "d3", "d7", "d8"], {"d1", "d3", "d5"}
assert precision_at_k(ret, rel, 5) == 0.4 and abs(recall_at_k(ret, rel, 5) - 2 / 3) < 1e-9
assert hit_rate_at_k(ret, rel, 5) == 1.0 and reciprocal_rank(ret, rel) == 1.0
assert abs(reciprocal_rank(["x", "y", "d3"], rel) - 1 / 3) < 1e-9
assert round(ndcg_at_k(ret, rel, 5), 3) == 0.704


def rrf(rankings, k=60):
    sc = defaultdict(float)
    for ranking in rankings:
        for pos, doc in enumerate(ranking, 1):
            sc[doc] += 1 / (k + pos)
    return sorted(sc.items(), key=lambda kv: -kv[1])
assert rrf([["a", "b", "c"], ["c", "a", "b"]])[0][0] == "a"

# 17) huge-number addition without trusting the LLM
x, y = 10**60 + 12345, 9 * 10**59 + 99999
assert x + y == int(str(x)) + int(str(y))


def add_strings(p, q):
    p, q = p[::-1], q[::-1]
    carry, out = 0, []
    for i in range(max(len(p), len(q))):
        tot = (int(p[i]) if i < len(p) else 0) + (int(q[i]) if i < len(q) else 0) + carry
        out.append(str(tot % 10)); carry = tot // 10
    if carry:
        out.append(str(carry))
    return "".join(reversed(out))
assert add_strings(str(x), str(y)) == str(x + y)

print("ALL SOLUTIONS VERIFIED")
