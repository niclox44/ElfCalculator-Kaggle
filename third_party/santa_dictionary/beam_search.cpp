// SPDX-License-Identifier: Apache-2.0
// Signed quotient/remainder search over expressions available in the current puzzle.
// Solver core by Tony Li (https://www.kaggle.com/code/tonylica/elf-calculator-with-register-reuse).
// Parameterized portfolio by konbu17:
// https://www.kaggle.com/code/konbu17/santa-2026-wider-dictionary-portfolio-163k
// Changes in this notebook: the four tunables below are read from the command line.
// Modified locally: replan all unfinished targets against each rebuilt dictionary,
// choose the cheapest arithmetic plan, and compile in that selected target order.
// Additional modes expose deterministic target-order experiments.
// Mode 6 repairs an input program's graph and keeps only shorter compiled results.
// Mode 7 also repairs internal hubs, ranked by measured full-program ablation cost.
// Mode 8 rebuilds complete exclusive ancestor cones against an exact outside cut.
// Mode 9 jointly destroys/replans groups of 6-10 outputs around the retained DAG.
// Original and parameterized notebooks are Apache-2.0 licensed; see
// licenses/Apache-2.0.txt and THIRD_PARTY.md for attribution and license details.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <map>
#include <memory>
#include <random>
#include <set>
#include <unordered_map>
#include <vector>
using namespace std;
using Int = int64_t;
static double ALPHA = 0.18;  // beam rank = instructions spent + ALPHA * log2(remaining integer)
static int N_DONE = 52;      // leaf budget after adding previous targets (largest first)
static int N_RECENT = 56;    // leaf budget after adding the most recent intermediate values
static int INDEX_BITS = 20;  // log2(slots) of the open-addressing index
static int ORDER_MODE = 1;  // 0: original, 1: cheapest remaining, 2: perturbed order,
                           // 3: affinity, 4: true register-allocated prefix cost,
                           // 5: true cost with resident-bank cached leaves
static uint64_t ORDER_SEED = 0;
static int REPAIR_TRIALS = 12;
static int REPAIR_PASSES = 1;
struct Expr {
    Int v;
    int a = -1, b = -1;
    char op = 0;
    int cost = 0;
};
Int apply(char op, Int a, Int b) {
    if (op == '+')
        return a + b;
    if (op == '-')
        return a - b;
    if (op == '/')
        return a / b;
    return a * b; // All callers check the puzzle limit before multiplying.
}
// Integer-key index reused between targets. Zero is outside the calculator domain.
struct Index {
    vector<Int> keys;
    vector<int> ids, used;
    size_t mask;
    Index(int bits) : keys(1u << bits), ids(keys.size()), mask(keys.size() - 1) {}
    size_t slot(Int v) const {
        uint64_t h = uint64_t(v) * 0x9e3779b97f4a7c15ULL;
        h ^= h >> 31;
        size_t i = h & mask;
        while (keys[i] && keys[i] != v)
            i = (i + 1) & mask;
        return i;
    }
    int get(Int v) const {
        size_t i = slot(v);
        return keys[i] ? ids[i] : -1;
    }
    bool insert(Int v, int id) {
        size_t i = slot(v);
        if (keys[i] || used.size() * 8 > keys.size() * 7) // never let the table fill up
            return false;
        used.push_back(i);
        keys[i] = v;
        ids[i] = id;
        return true;
    }
    void clear() {
        for (int i : used)
            keys[i] = 0;
        used.clear();
    }
};
struct Dictionary {
    Int limit;
    Index index{INDEX_BITS};
    vector<Expr> e;
    array<vector<pair<Int, int>>, 3> sorted;
    int n0 = 0, n1 = 0;
    explicit Dictionary(Int limit) : limit(limit) {}
    void add(Int v, int a, int b, char op, int cost) {
        if (v > 0 && v <= limit && index.insert(v, e.size()))
            e.push_back({v, a, b, op, cost});
    }
    void combine(int i, int j, int cost) {
        Int a = e[i].v, b = e[j].v;
        add(a + b, i, j, '+', cost);
        if (a != b)
            add(abs(a - b), a > b ? i : j, a > b ? j : i, '-', cost);
        if (a <= limit / b)
            add(a * b, i, j, '*', cost);
        if (a > b && a % b == 0)
            add(a / b, i, j, '/', cost);
        if (b > a && b % a == 0)
            add(b / a, j, i, '/', cost);
        if ((ORDER_MODE == 7 || ORDER_MODE == 8) && a == b)
            add(1, i, j, '/', cost);
    }
    void build(const vector<Int> &leaves) {
        index.clear();
        e.clear();
        for (auto &s : sorted)
            s.clear();
        for (Int v : leaves)
            add(v, -1, -1, 0, 0);
        n0 = e.size();
        for (int i = 0; i < n0; i++)
            for (int j = 0; j <= i; j++)
                combine(i, j, 1);
        n1 = e.size();
        for (int i = n0; i < n1; i++)
            for (int j = 0; j < n0; j++)
                combine(i, j, 2);
        for (int i = 0; i < int(e.size()); i++)
            sorted[e[i].cost].emplace_back(e[i].v, i);
        for (auto &s : sorted)
            sort(s.begin(), s.end());
    }
};
// A reduction encodes parent = (child * factor) +/- atom, or atom - child.
struct Link {
    int factor = -1, atom = -1;
    char op = '+';
};
struct State {
    Int v;
    int cost = 0, parent = -1;
    Link link;
    double rank = 0;
};
struct Search {
    Dictionary &d;
    int width, best = 1000, end = -1, terminal = -1;
    vector<State> history, next;
    unordered_map<Int, int> visited;
    Search(Dictionary &d, int width) : d(d), width(width) {}
    int expr_cost(int id) const { return id < 0 ? 0 : 1 + d.e[id].cost; }
    void offer(int p, Int v, int f, int a, char op) {
        if (v <= 0 || v > d.limit)
            return;
        int cost = history[p].cost + expr_cost(f) + expr_cost(a);
        if (cost >= best)
            return;
        int t = d.index.get(v);
        if (t >= 0) {
            if (cost + d.e[t].cost < best) {
                best = cost + d.e[t].cost;
                end = history.size();
                terminal = t;
                history.push_back({v, cost, p, {f, a, op}});
            }
            return;
        }
        if (cost + 3 >= best || v >= history[p].v)
            return;
        // Comparisons happen across instruction costs and residual sizes.
        double rank = cost + ALPHA * log2(double(v));
        if (int(next.size()) == width && rank >= next.back().rank)
            return;
        auto prev = visited.find(v);
        if (prev != visited.end() && prev->second <= cost)
            return;
        for (auto it = next.begin(); it != next.end(); ++it)
            if (it->v == v) {
                if (it->cost <= cost)
                    return;
                next.erase(it);
                break;
            }
        State s{v, cost, p, {f, a, op}, rank};
        auto it = upper_bound(next.begin(), next.end(), rank,
                              [](double k, const State &x) { return k < x.rank; });
        next.insert(it, s);
        if (int(next.size()) > width)
            next.pop_back();
    }
    void expand(int p) {
        Int v = history[p].v;
        for (auto &arr : d.sorted) {
            auto it = lower_bound(arr.begin(), arr.end(), make_pair(v, -1));
            for (int k = -4; k < 4; k++) {
                auto pos = (it - arr.begin()) + k;
                if (pos < 0 || pos >= int(arr.size()))
                    continue;
                auto [a, id] = arr[pos];
                offer(p, abs(v - a), -1, id, v > a ? '+' : 'r');
            }
        }
        for (int i = 0; i < d.n1; i++) {
            Int a = d.e[i].v;
            if (a == 1)
                continue;
            Int diff = abs(v - a);
            if (diff) {
                if (d.index.get(diff) >= 0)
                    offer(p, diff, -1, i, v > a ? '+' : 'r');
                if (v > a && (diff & 15) == 0)
                    shifted(p, diff, i, '+');
                if (a > v && (diff & 15) == 0)
                    shifted(p, diff, i, 'r');
            }
            if (a + v <= d.limit) {
                if (d.index.get(a + v) >= 0)
                    offer(p, a + v, -1, i, '-');
                if (((a + v) & 15) == 0)
                    shifted(p, a + v, i, '-');
            }
            if (a >= v)
                continue;
            Int q = v / a, r = v % a;
            if (!r) {
                offer(p, q, i, -1, '+');
                continue;
            }
            int rid = d.index.get(r);
            if (rid >= 0)
                offer(p, q, i, rid, '+');
            if (a - r <= d.limit - v) {
                rid = d.index.get(a - r);
                if (rid >= 0)
                    offer(p, q + 1, i, rid, '-');
            }
            // Approximate the quotient by a cached expression, then synthesize the error.
            if (i < d.n0 && q > 64) {
                for (auto &arr : d.sorted) {
                    auto it = lower_bound(arr.begin(), arr.end(), make_pair(q, -1));
                    for (int k = -1; k <= 0; k++) {
                        auto pos = (it - arr.begin()) + k;
                        if (pos < 0 || pos >= int(arr.size()))
                            continue;
                        auto [b, bi] = arr[pos];
                        if (b > d.limit / a)
                            continue;
                        Int mul = a * b;
                        if (mul == v)
                            continue;
                        int id = d.index.get(mul);
                        if (id >= 0)
                            offer(p, abs(mul - v), -1, id, mul < v ? '+' : 'r');
                    }
                }
            }
        }
    }
    void shifted(int p, Int diff, int atom, char op) {
        int k = __builtin_ctzll(diff);
        while (k >= 4) {
            int f = d.index.get(Int(1) << k);
            if (f >= 0) {
                offer(p, diff >> k, f, atom, op);
                break;
            }
            k--;
        }
    }
    void run(Int target) {
        history.push_back({target, 0, -1, {}});
        int id = d.index.get(target);
        if (id >= 0) {
            end = 0;
            terminal = id;
            best = d.e[id].cost;
            return;
        }
        vector<int> front{0};
        for (int depth = 0; depth < 20 && !front.empty(); depth++) {
            next.clear();
            for (int p : front)
                if (history[p].cost + 3 < best)
                    expand(p);
            front.clear();
            for (State s : next) {
                if (s.cost + 3 >= best)
                    continue;
                visited[s.v] = s.cost;
                front.push_back(history.size());
                history.push_back(s);
            }
        }
    }
};
struct Puzzle {
    Int limit;
    vector<Int> starts, targets, palette;
    map<Int, Expr> defs;
    vector<Int> order;
    int width;
    Puzzle(Int limit, int width) : limit(limit), width(width) {}
    Int make(char op, Int a, Int b) {
        Int v = apply(op, a, b);
        if (v <= 0 || v > limit)
            throw runtime_error("invalid construction");
        if (!defs.count(v)) {
            defs[v] = {v, -1, -1, op};
            args[v] = {a, b};
            order.push_back(v);
        }
        return v;
    }
    map<Int, pair<Int, Int>> args;
    Int power(int k) {
        Int v = Int(1) << k;
        if (defs.count(v))
            return v;
        if (k == 1)
            return make('+', 1, 1);
        Int right = power(k - k / 2);
        Int left = power(k / 2);
        return make('*', left, right);
    }
    void setup() {
        for (Int v : starts)
            defs[v] = {v};
        if (!defs.count(1))
            make('/', starts[0], starts[0]);
        palette = {1};
        for (int k : {1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 20, 24, 32, 40, 48}) {
            if ((Int(1) << k) <= limit)
                palette.push_back(power(k));
        }
        for (int i : {3, 5, 7, 9, 11, 13, 15, 17, 19, 23, 31})
            if (i <= limit) {
                if (!defs.count(i)) {
                    if (i == 11 || i == 13 || i == 19 || i == 23)
                        make('+', i - (i == 23 ? 16 : 8), i == 23 ? 16 : 8);
                    else if ((i & (i + 1)) == 0 && i + 1 <= limit)
                        make('-', i + 1, 1);
                    else
                        binary(i);
                }
                palette.push_back(i);
            }
    }
    Int materialize(Dictionary &d, int id) {
        const Expr &e = d.e[id];
        if (defs.count(e.v))
            return e.v;
        Int right = materialize(d, e.b);
        Int left = materialize(d, e.a);
        return make(e.op, left, right);
    }
    Int binary(Int v) {
        if (defs.count(v))
            return v;
        Int h = binary(v / 2);
        Int twice = make('+', h, h);
        return v % 2 ? make('+', twice, 1) : twice;
    }
    void solve() {
        if (ORDER_MODE == 2) {
            if (ORDER_SEED == 0)
                reverse(targets.begin(), targets.end());
            else {
                mt19937_64 generator(ORDER_SEED);
                shuffle(targets.begin(), targets.end(), generator);
            }
        }
        if (ORDER_MODE == 1 || ORDER_MODE == 3 || ORDER_MODE == 4 || ORDER_MODE == 5) {
            solve_replanned();
            return;
        }
        setup();
        Dictionary d(limit);
        set<Int> done;
        for (Int target : targets) {
            if (!defs.count(target)) {
                vector<Int> leaves;
                set<Int> used;
                auto add = [&](Int v) {
                    if (used.insert(v).second)
                        leaves.push_back(v);
                };
                for (Int v : palette)
                    add(v);
                for (Int v : starts)
                    add(v);
                for (auto it = done.rbegin(); it != done.rend() && int(leaves.size()) < N_DONE; ++it)
                    add(*it);
                for (auto it = order.rbegin(); it != order.rend() && int(leaves.size()) < N_RECENT; ++it)
                    add(*it);
                d.build(leaves);
                Search s(d, width);
                s.run(target);
                if (s.end < 0)
                    binary(target);
                else {
                    Int v = materialize(d, s.terminal);
                    for (int p = s.end; s.history[p].parent >= 0; p = s.history[p].parent) {
                        Link l = s.history[p].link;
                        if (l.factor >= 0)
                            v = make('*', v, materialize(d, l.factor));
                        if (l.atom >= 0) {
                            Int a = materialize(d, l.atom);
                            v = l.op == 'r' ? make('-', a, v) : make(l.op, v, a);
                        }
                    }
                    if (v != target)
                        throw runtime_error("search reconstruction failed");
                }
            }
            done.insert(target);
        }
    }
    void solve_replanned() {
        setup();
        Dictionary d(limit);
        set<Int> done;
        vector<Int> pending = targets, schedule;
        mt19937_64 generator(ORDER_SEED);
        if (ORDER_SEED)
            shuffle(pending.begin(), pending.end(), generator);
        while (!pending.empty()) {
            // A previous target may have materialized additional targets.
            for (auto it = pending.begin(); it != pending.end();) {
                if (defs.count(*it)) {
                    done.insert(*it);
                    schedule.push_back(*it);
                    it = pending.erase(it);
                } else
                    ++it;
            }
            if (pending.empty())
                break;
            vector<Int> leaves;
            set<Int> used;
            auto add = [&](Int v) {
                if (used.insert(v).second)
                    leaves.push_back(v);
            };
            for (Int v : palette)
                add(v);
            for (Int v : starts)
                add(v);
            set<Int> resident;
            if (ORDER_MODE == 5 && !schedule.empty()) {
                Puzzle prefix = *this;
                prefix.targets = schedule;
                array<Int, 48> bank{};
                copy(starts.begin(), starts.end(), bank.begin());
                for (auto instruction : prefix.compile()) {
                    auto [operation, left, right, destination] = instruction;
                    bank[destination] = apply(char(operation), bank[left], bank[right]);
                }
                for (Int value : bank)
                    if (value)
                        resident.insert(value);
            }
            for (auto it = done.rbegin(); it != done.rend() && int(leaves.size()) < N_DONE; ++it)
                if (resident.empty() || resident.count(*it))
                    add(*it);
            for (auto it = order.rbegin(); it != order.rend() && int(leaves.size()) < N_RECENT; ++it)
                if (resident.empty() || resident.count(*it))
                    add(*it);
            d.build(leaves);
            unique_ptr<Search> best_search;
            size_t selected = 0;
            double best_rank = 1e30;
            for (size_t index = 0; index < pending.size(); ++index) {
                auto candidate = make_unique<Search>(d, width);
                candidate->run(pending[index]);
                double rank = candidate->end < 0 ? 2 * log2(double(pending[index])) : candidate->best;
                // Mode 3 favors a cheap target whose value has several nearby
                // unfinished targets, exposing inexpensive subsequent deltas.
                if (ORDER_MODE == 3) {
                    double affinity = 0;
                    for (Int target : pending) {
                        Int difference = abs(target - pending[index]);
                        if (difference && d.index.get(difference) >= 0)
                            affinity += 1.0 / (1 + d.e[d.index.get(difference)].cost);
                    }
                    rank -= min(2.0, affinity * .25);
                }
                if (ORDER_MODE == 4 || ORDER_MODE == 5) {
                    // The dictionary treats all selected leaves as free. Some
                    // are unneeded palette entries; others have been evicted
                    // from the physical bank. Compile a hypothetical prefix
                    // to charge their actual construction and reload costs.
                    Puzzle trial = *this;
                    Int target = pending[index];
                    if (candidate->end < 0)
                        trial.binary(target);
                    else
                        trial.reconstruct(d, *candidate, target);
                    trial.targets = schedule;
                    trial.targets.push_back(target);
                    rank = trial.compile().size() + candidate->best * .0001;
                }
                if (rank < best_rank) {
                    best_rank = rank;
                    selected = index;
                    best_search = std::move(candidate);
                }
            }
            Int target = pending[selected];
            if (best_search->end < 0)
                binary(target);
            else
                reconstruct(d, *best_search, target);
            done.insert(target);
            schedule.push_back(target);
            pending.erase(pending.begin() + selected);
        }
        targets = std::move(schedule);
    }
    void reconstruct(Dictionary &dictionary, Search &search, Int target) {
        Int value = materialize(dictionary, search.terminal);
        for (int p = search.end; search.history[p].parent >= 0; p = search.history[p].parent) {
            Link link = search.history[p].link;
            if (link.factor >= 0)
                value = make('*', value, materialize(dictionary, link.factor));
            if (link.atom >= 0) {
                Int atom = materialize(dictionary, link.atom);
                value = link.op == 'r' ? make('-', atom, value) : make(link.op, value, atom);
            }
        }
        if (value != target)
            throw runtime_error("replanned search reconstruction failed");
    }
    void load_hint(const vector<array<int, 4>> &hint) {
        if (starts.empty() || starts.size() > 48 || hint.size() > 4096)
            throw runtime_error("invalid hint dimensions");
        defs.clear();
        args.clear();
        order.clear();
        palette.clear();
        array<Int, 48> bank{};
        set<Int> covered;
        for (size_t index = 0; index < starts.size(); ++index) {
            Int value = starts[index];
            if (value <= 0 || value > limit)
                throw runtime_error("invalid initial hint value");
            bank[index] = value;
            defs[value] = {value};
            covered.insert(value);
        }
        for (auto instruction : hint) {
            auto [operation, left, right, destination] = instruction;
            if (left < 0 || left >= 48 || right < 0 || right >= 48 || destination < 0 || destination >= 48)
                throw runtime_error("invalid hint register");
            Int a = bank[left], b = bank[right];
            if (!a || !b)
                throw runtime_error("undefined hint source");
            if (operation != '+' && operation != '-' && operation != '*' && operation != '/')
                throw runtime_error("invalid hint operator");
            if ((operation == '-' && a <= b) || (operation == '/' && a % b) ||
                (operation == '*' && a > limit / b))
                throw runtime_error("illegal hint arithmetic");
            Int value = make(char(operation), a, b);
            bank[destination] = value;
            covered.insert(value);
        }
        for (Int target : targets)
            if (!covered.count(target))
                throw runtime_error("hint does not cover every target");
    }
    set<Int> descendants(Int target) const {
        map<Int, vector<Int>> users;
        for (auto &[value, operands] : args) {
            users[operands.first].push_back(value);
            if (operands.first != operands.second)
                users[operands.second].push_back(value);
        }
        set<Int> blocked{target};
        vector<Int> queue{target};
        for (size_t index = 0; index < queue.size(); ++index)
            for (Int user : users[queue[index]])
                if (blocked.insert(user).second)
                    queue.push_back(user);
        return blocked;
    }
    vector<array<int, 4>> polish_hint(const vector<array<int, 4>> &hint) {
        load_hint(hint);
        auto best_program = hint;
        try {
            auto normalized = compile();
            if (normalized.size() < best_program.size())
                best_program = std::move(normalized);
        } catch (const exception &) {
            // The original hint may legally overwrite every seed register.
            // The inherited allocator protects seeds, so retain such a hint.
        }
        Dictionary dictionary(limit);
        mt19937_64 generator(ORDER_SEED);
        for (int pass = 0; pass < REPAIR_PASSES; ++pass) {
            // Count target ancestry to prioritize large exclusive branches.
            map<Int, int> target_uses, fanout;
            map<Int, set<Int>> ancestors;
            for (auto &[value, operands] : args) {
                ++fanout[operands.first];
                ++fanout[operands.second];
            }
            for (Int target : targets) {
                auto visit = [&](auto &&self, Int value) -> void {
                    if (!ancestors[target].insert(value).second)
                        return;
                    ++target_uses[value];
                    auto found = args.find(value);
                    if (found != args.end()) {
                        self(self, found->second.first);
                        self(self, found->second.second);
                    }
                };
                visit(visit, target);
            }
            vector<pair<int, Int>> ranked;
            if (ORDER_MODE == 7 || ORDER_MODE == 8) {
                set<Int> target_set(targets.begin(), targets.end());
                map<Int, int> tree_cost;
                auto estimate = [&](auto &&self, Int value) -> int {
                    auto cached = tree_cost.find(value);
                    if (cached != tree_cost.end())
                        return cached->second;
                    auto operands = args.find(value);
                    if (operands == args.end())
                        return tree_cost[value] = 0;
                    auto [a, b] = operands->second;
                    int cost = 1 + self(self, a) + (a == b ? 0 : self(self, b));
                    return tree_cost[value] = min(10000, cost);
                };
                vector<pair<int, Int>> coarse;
                for (auto &[value, operands] : args)
                    if (target_uses[value]) {
                        int priority = estimate(estimate, value) * min(4, target_uses[value]);
                        coarse.push_back({-priority, value});
                    }
                sort(coarse.begin(), coarse.end());
                size_t pool_limit = min(size_t(512), size_t(max(64, REPAIR_TRIALS * 8)));
                if (coarse.size() > pool_limit)
                    coarse.resize(pool_limit);
                int current_cost = best_program.size();
                try {
                    current_cost = compile().size();
                } catch (const exception &) {
                }
                // A free extra seed is a relaxation, used only to rank hubs.
                // Real replacements still pay every operation and register.
                for (auto [priority, value] : coarse) {
                    if (starts.size() >= 48)
                        break;
                    Puzzle ablated = *this;
                    ablated.starts.push_back(value);
                    ablated.args.erase(value);
                    try {
                        int removed = current_cost - int(ablated.compile().size());
                        if (removed > 1)
                            ranked.push_back({-(removed * 8 + min(7, fanout[value])), value});
                    } catch (const exception &) {
                    }
                }
                sort(ranked.begin(), ranked.end());
                if (ORDER_SEED % 3 == 1) {
                    size_t exploration = min(ranked.size(), size_t(max(16, REPAIR_TRIALS * 3)));
                    shuffle(ranked.begin(), ranked.begin() + exploration, generator);
                } else if (ORDER_SEED % 3 == 2) {
                    stable_sort(ranked.begin(), ranked.end(), [&](auto a, auto b) {
                        return make_pair(target_uses[a.second], -a.first) >
                               make_pair(target_uses[b.second], -b.first);
                    });
                }
                vector<pair<int, Int>> hubs, outputs;
                for (auto candidate : ranked)
                    (target_set.count(candidate.second) ? outputs : hubs).push_back(candidate);
                ranked.clear();
                size_t hub_budget = min(hubs.size(), size_t((REPAIR_TRIALS * 3 + 3) / 4));
                ranked.insert(ranked.end(), hubs.begin(), hubs.begin() + hub_budget);
                size_t output_budget = min(outputs.size(), size_t(REPAIR_TRIALS) - hub_budget);
                ranked.insert(ranked.end(), outputs.begin(), outputs.begin() + output_budget);
                for (size_t index = hub_budget; index < hubs.size() && ranked.size() < size_t(REPAIR_TRIALS); ++index)
                    ranked.push_back(hubs[index]);
                for (size_t index = output_budget; index < outputs.size() && ranked.size() < size_t(REPAIR_TRIALS); ++index)
                    ranked.push_back(outputs[index]);
            } else {
                for (Int target : targets) {
                    if (!args.count(target))
                        continue;
                    int exclusive = 0;
                    for (Int value : ancestors[target])
                        if (args.count(value) && target_uses[value] == 1)
                            ++exclusive;
                    ranked.push_back({-exclusive, target});
                }
                sort(ranked.begin(), ranked.end());
                if (ORDER_SEED % 3 == 1)
                    shuffle(ranked.begin(), ranked.end(), generator);
                else if (ORDER_SEED % 3 == 2)
                    stable_sort(ranked.begin(), ranked.end(), [&](auto a, auto b) {
                        return ancestors[a.second].size() > ancestors[b.second].size();
                    });
            }
            size_t attempts = min(ranked.size(), size_t(REPAIR_TRIALS));
            bool improved = false;
            for (size_t attempt = 0; attempt < attempts; ++attempt) {
                Int target = ranked[attempt].second;
                set<Int> blocked = descendants(target);
                set<Int> outside;
                vector<Int> cut_boundary;
                if (ORDER_MODE == 8) {
                    // All values still required when this hub is treated as a
                    // free input are truly shared with the outside program.
                    // The other ancestors form the full removable cone. This
                    // includes diamonds whose nodes have several uses inside
                    // the cone, unlike a fanout-one/depth-limited tree cut.
                    auto visit_outside = [&](auto &&self, Int value) -> void {
                        if (!outside.insert(value).second || value == target)
                            return;
                        auto found = args.find(value);
                        if (found != args.end()) {
                            self(self, found->second.first);
                            self(self, found->second.second);
                        }
                    };
                    for (Int output : targets)
                        visit_outside(visit_outside, output);
                    set<Int> cone;
                    auto visit_cone = [&](auto &&self, Int value) -> void {
                        if (value != target && outside.count(value)) {
                            cut_boundary.push_back(value);
                            return;
                        }
                        if (!cone.insert(value).second)
                            return;
                        auto found = args.find(value);
                        if (found != args.end()) {
                            self(self, found->second.first);
                            self(self, found->second.second);
                        } else {
                            // Initial inputs remain available without cost.
                            outside.insert(value);
                            cut_boundary.push_back(value);
                        }
                    };
                    visit_cone(visit_cone, target);
                    for (Int value : cone)
                        if (args.count(value)) {
                            auto excluded = descendants(value);
                            blocked.insert(excluded.begin(), excluded.end());
                        }
                }
                if (ORDER_MODE == 7) {
                    // Do not expose an expensive original operand as a free
                    // dictionary leaf: that makes the old one-step root recipe
                    // an immediate terminal and prevents context rewriting.
                    map<Int, int> live_fanout;
                    for (auto &[value, operands] : args)
                        if (target_uses[value]) {
                            ++live_fanout[operands.first];
                            if (operands.first != operands.second)
                                ++live_fanout[operands.second];
                        }
                    set<Int> required_targets(targets.begin(), targets.end());
                    vector<Int> frontier{target};
                    set<Int> roots{target};
                    int context_depth = 3 + int(ORDER_SEED % 3);
                    for (int depth = 0; depth < context_depth && !frontier.empty(); ++depth) {
                        vector<Int> following;
                        for (Int root : frontier) {
                            auto operands = args.find(root);
                            if (operands == args.end())
                                continue;
                            for (Int parent : {operands->second.first, operands->second.second})
                                if (args.count(parent) && !required_targets.count(parent) &&
                                    live_fanout[parent] == 1 && roots.insert(parent).second) {
                                    following.push_back(parent);
                                    auto excluded = descendants(parent);
                                    blocked.insert(excluded.begin(), excluded.end());
                                }
                        }
                        frontier = std::move(following);
                    }
                }
                vector<Int> leaves;
                set<Int> used;
                auto add = [&](Int value) {
                    if (defs.count(value) && !blocked.count(value) &&
                        (ORDER_MODE != 8 || outside.count(value) ||
                         find(starts.begin(), starts.end(), value) != starts.end()) &&
                        used.insert(value).second)
                        leaves.push_back(value);
                };
                for (Int value : starts)
                    add(value);
                if (ORDER_MODE == 8) {
                    sort(cut_boundary.begin(), cut_boundary.end(), greater<Int>());
                    for (Int value : cut_boundary)
                        if (int(leaves.size()) < N_RECENT)
                            add(value);
                }
                add(1);
                for (int exponent : {1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 20, 24, 32, 40, 48})
                    add(Int(1) << exponent);
                for (int value : {3, 5, 7, 9, 11, 13, 15, 17, 19, 23, 31})
                    add(value);
                // Other completed targets supply useful large free atoms.
                for (auto it = targets.rbegin(); it != targets.rend() && int(leaves.size()) < N_DONE; ++it)
                    add(*it);
                vector<pair<int, Int>> intermediates;
                for (auto &[value, expression] : defs)
                    if (!blocked.count(value) && !used.count(value))
                        intermediates.push_back({-fanout[value], value});
                sort(intermediates.begin(), intermediates.end());
                if (ORDER_SEED % 2)
                    reverse(intermediates.begin(), intermediates.end());
                for (auto [utility, value] : intermediates) {
                    if (int(leaves.size()) >= N_RECENT)
                        break;
                    add(value);
                }
                dictionary.build(leaves);
                Search search(dictionary, width);
                search.run(target);
                if (search.end < 0)
                    continue;
                Puzzle trial = *this;
                map<Int, Expr> removed_defs;
                map<Int, pair<Int, Int>> removed_args;
                for (Int value : blocked) {
                    removed_defs[value] = trial.defs.at(value);
                    auto operands = trial.args.find(value);
                    if (operands != trial.args.end())
                        removed_args[value] = operands->second;
                    trial.defs.erase(value);
                    trial.args.erase(value);
                }
                // A derived dictionary atom can equal an old descendant. It
                // must receive the dictionary's independent recipe rather
                // than silently reusing a recipe that still depends on T.
                trial.reconstruct(dictionary, search, target);
                for (auto &[value, expression] : removed_defs)
                    if (!trial.defs.count(value)) {
                        trial.defs[value] = expression;
                        auto operands = removed_args.find(value);
                        if (operands != removed_args.end())
                            trial.args[value] = operands->second;
                    }
                try {
                    auto candidate = trial.compile();
                    if (candidate.size() < best_program.size()) {
                        best_program = std::move(candidate);
                        *this = std::move(trial);
                        improved = true;
                    }
                } catch (const exception &) {
                    // Preserve the validated hint when allocation cannot fit.
                }
            }
            if (!improved)
                break;
        }
        return best_program;
    }
    vector<array<int, 4>> polish_tail_hint(const vector<array<int, 4>> &hint) {
        load_hint(hint);
        auto best_program = hint;
        try {
            auto normalized = compile();
            if (normalized.size() < best_program.size())
                best_program = std::move(normalized);
        } catch (const exception &) {
            // Some valid hints overwrite all seeds; the protected-seed
            // allocator cannot always reproduce those and must retain them.
        }
        mt19937_64 generator(ORDER_SEED ^ 0x9e3779b97f4a7c15ULL);
        for (int pass = 0; pass < REPAIR_PASSES; ++pass) {
            bool improved = false;
            for (int attempt = 0; attempt < REPAIR_TRIALS; ++attempt) {
                // Restore the accepted instruction stream so every trial sees
                // a compact, acyclic graph without stale discarded recipes.
                load_hint(best_program);
                set<Int> required(targets.begin(), targets.end()), seen;
                vector<Int> completion;
                auto add_output = [&](Int value) {
                    if (required.count(value) && seen.insert(value).second)
                        completion.push_back(value);
                };
                for (Int value : starts)
                    add_output(value);
                for (Int value : order)
                    add_output(value);
                for (Int value : targets)
                    add_output(value);
                if (completion.empty())
                    return best_program;
                size_t group_size = min(completion.size(), size_t(6 + (attempt + ORDER_SEED) % 5));
                vector<Int> chosen;
                if (attempt % 3 == 2) {
                    chosen = completion;
                    shuffle(chosen.begin(), chosen.end(), generator);
                    chosen.resize(group_size);
                } else {
                    size_t offset = completion.size() - group_size;
                    if (attempt % 3 == 1 && offset)
                        offset = generator() % (offset + 1);
                    chosen.assign(completion.begin() + offset, completion.begin() + offset + group_size);
                }
                set<Int> removed_outputs(chosen.begin(), chosen.end());
                vector<Int> prefix;
                for (Int value : completion)
                    if (!removed_outputs.count(value))
                        prefix.push_back(value);
                set<Int> outside(starts.begin(), starts.end());
                auto visit = [&](auto &&self, Int value) -> void {
                    if (!outside.insert(value).second)
                        return;
                    auto operands = args.find(value);
                    if (operands != args.end()) {
                        self(self, operands->second.first);
                        self(self, operands->second.second);
                    }
                };
                for (Int value : prefix)
                    visit(visit, value);
                Puzzle trial = *this;
                for (auto it = trial.defs.begin(); it != trial.defs.end();)
                    if (!outside.count(it->first))
                        it = trial.defs.erase(it);
                    else
                        ++it;
                for (auto it = trial.args.begin(); it != trial.args.end();)
                    if (!outside.count(it->first))
                        it = trial.args.erase(it);
                    else
                        ++it;
                trial.order.erase(remove_if(trial.order.begin(), trial.order.end(),
                                            [&](Int value) { return !outside.count(value); }),
                                  trial.order.end());
                trial.targets = prefix;
                vector<Int> schedule = prefix, pending = chosen;
                if ((attempt + ORDER_SEED) % 2)
                    shuffle(pending.begin(), pending.end(), generator);
                try {
                    // Only retained values are genuinely free. Eagerly adding
                    // the usual palette makes an unused 2 or 3 appear free and
                    // can hide a cheaper doubling/addition behind x*2/x*3.
                    // The dictionary itself constructs one/two-step constants;
                    // one shared unit is the sole optional initial investment.
                    trial.palette.clear();
                    if (!trial.defs.count(1))
                        trial.make('/', starts[0], starts[0]);
                    trial.palette.push_back(1);
                    for (int exponent : {1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 20, 24, 32, 40, 48})
                        if (trial.defs.count(Int(1) << exponent))
                            trial.palette.push_back(Int(1) << exponent);
                    for (int value : {3, 5, 7, 9, 11, 13, 15, 17, 19, 23, 31})
                        if (trial.defs.count(value))
                            trial.palette.push_back(value);
                    Dictionary dictionary(limit);
                    bool viable = true;
                    while (!pending.empty()) {
                        for (auto it = pending.begin(); it != pending.end();)
                            if (trial.defs.count(*it)) {
                                schedule.push_back(*it);
                                it = pending.erase(it);
                            } else
                                ++it;
                        if (pending.empty())
                            break;
                        vector<Int> leaves;
                        set<Int> used;
                        auto add = [&](Int value) {
                            if (trial.defs.count(value) && used.insert(value).second)
                                leaves.push_back(value);
                        };
                        for (Int value : trial.palette)
                            add(value);
                        for (Int value : starts)
                            add(value);
                        for (auto it = schedule.rbegin(); it != schedule.rend() && int(leaves.size()) < N_DONE; ++it)
                            add(*it);
                        for (auto it = trial.order.rbegin(); it != trial.order.rend() && int(leaves.size()) < N_RECENT; ++it)
                            add(*it);
                        dictionary.build(leaves);
                        unique_ptr<Puzzle> selected;
                        size_t selected_index = 0;
                        double best_rank = 1e30;
                        for (size_t index = 0; index < pending.size(); ++index) {
                            Search search(dictionary, width);
                            search.run(pending[index]);
                            Puzzle candidate = trial;
                            if (search.end < 0)
                                candidate.binary(pending[index]);
                            else
                                candidate.reconstruct(dictionary, search, pending[index]);
                            candidate.targets = schedule;
                            candidate.targets.push_back(pending[index]);
                            try {
                                auto partial = candidate.compile();
                                // Register reload counts are not a monotone
                                // bound as more future uses become known.
                                // Only the distinct required arithmetic nodes
                                // give a safe lower bound for this prefix DAG.
                                set<Int> active(candidate.starts.begin(), candidate.starts.end());
                                size_t arithmetic_nodes = 0;
                                auto count = [&](auto &&self, Int value) -> void {
                                    if (!active.insert(value).second)
                                        return;
                                    auto operands = candidate.args.find(value);
                                    if (operands == candidate.args.end())
                                        throw runtime_error("incomplete tail prefix");
                                    ++arithmetic_nodes;
                                    self(self, operands->second.first);
                                    self(self, operands->second.second);
                                };
                                for (Int output : candidate.targets)
                                    count(count, output);
                                if (arithmetic_nodes >= best_program.size())
                                    continue;
                                int covered = 0;
                                for (Int value : pending)
                                    covered += candidate.defs.count(value);
                                double rank = partial.size() - .4 * covered + .0001 * search.best;
                                if (rank < best_rank) {
                                    best_rank = rank;
                                    selected_index = index;
                                    selected = make_unique<Puzzle>(std::move(candidate));
                                }
                            } catch (const exception &) {
                            }
                        }
                        if (!selected) {
                            viable = false;
                            break;
                        }
                        schedule.push_back(pending[selected_index]);
                        pending.erase(pending.begin() + selected_index);
                        trial = std::move(*selected);
                    }
                    if (!viable)
                        continue;
                    trial.targets = schedule;
                    auto candidate = trial.compile();
                    if (candidate.size() < best_program.size()) {
                        best_program = std::move(candidate);
                        improved = true;
                    }
                } catch (const exception &) {
                    // A failed neighborhood cannot invalidate the accepted
                    // program. All trial construction happens on a copy.
                }
            }
            if (!improved)
                break;
        }
        return best_program;
    }
    // Walk dependencies on demand, then allocate registers by their next use.
    // An evicted value can always be rebuilt from its expression or a protected seed.
    vector<array<int, 4>> compile() {
        set<Int> placed(starts.begin(), starts.end());
        vector<Int> sequence;
        auto visit = [&](auto &&self, Int v) -> void {
            if (!placed.insert(v).second)
                return;
            auto [a, b] = args.at(v);
            self(self, a);
            self(self, b);
            sequence.push_back(v);
        };
        for (Int t : targets)
            visit(visit, t);
        map<Int, vector<int>> uses;
        for (int i = int(sequence.size()) - 1; i >= 0; --i) {
            auto [a, b] = args.at(sequence[i]);
            uses[a].push_back(i);
            if (a != b)
                uses[b].push_back(i);
        }
        array<Int, 48> bank{};
        set<Int> seeds(starts.begin(), starts.end());
        copy(starts.begin(), starts.end(), bank.begin());
        vector<array<int, 4>> program;
        auto emit = [&](auto &&self, Int v, uint64_t locked) -> int {
            auto found = find(bank.begin(), bank.end(), v);
            if (found != bank.end())
                return found - bank.begin();
            auto [a, b] = args.at(v);
            int ra = self(self, a, locked), rb = self(self, b, locked | (1ULL << ra));
            int rd = -1, latest = -1;
            for (int k = 0; k < 48; k++) {
                Int old = bank[k];
                if ((locked >> k & 1) || seeds.count(old))
                    continue;
                int nextuse = uses[old].empty() ? 1000000 : uses[old].back();
                if (!old) {
                    rd = k;
                    break;
                }
                if (nextuse > latest) {
                    rd = k;
                    latest = nextuse;
                }
            }
            if (rd < 0)
                throw runtime_error("register allocation failed");
            bank[rd] = v;
            program.push_back({defs.at(v).op, ra, rb, rd});
            return rd;
        };
        for (Int v : sequence) {
            auto [a, b] = args.at(v);
            uses[a].pop_back();
            if (a != b)
                uses[b].pop_back();
            emit(emit, v, 0);
        }
        return program;
    }
};
int main(int argc, char **argv) try {
    int width = argc > 1 ? stoi(argv[1]) : 3;
    if (argc > 2) ALPHA = stod(argv[2]);
    if (argc > 3) N_DONE = stoi(argv[3]);
    if (argc > 4) N_RECENT = stoi(argv[4]);
    if (argc > 5) INDEX_BITS = stoi(argv[5]);
    if (argc > 6) ORDER_MODE = stoi(argv[6]);
    if (argc > 7) ORDER_SEED = stoull(argv[7]);
    if (argc > 8) REPAIR_TRIALS = stoi(argv[8]);
    if (argc > 9) REPAIR_PASSES = stoi(argv[9]);
    if (REPAIR_TRIALS < 0 || REPAIR_TRIALS > 4096 || REPAIR_PASSES < 1 || REPAIR_PASSES > 100)
        throw runtime_error("invalid repair budget");
    string id;
    Int limit;
    int ns, nt;
    while (cin >> id >> limit >> ns >> nt) {
        if (limit < 1 || limit > 1000000000000000000LL || ns < 1 || ns > 48 || nt < 0 || nt > 4096)
            throw runtime_error("invalid puzzle dimensions");
        Puzzle p(limit, width);
        p.starts.resize(ns);
        p.targets.resize(nt);
        for (auto &x : p.starts)
            cin >> x;
        for (auto &x : p.targets)
            cin >> x;
        vector<array<int, 4>> prog;
        if (ORDER_MODE == 6 || ORDER_MODE == 7 || ORDER_MODE == 8 || ORDER_MODE == 9) {
            int count;
            if (!(cin >> count) || count < 0 || count > 4096)
                throw runtime_error("invalid hint instruction count");
            vector<array<int, 4>> hint;
            for (int number = 0; number < count; ++number) {
                char operation;
                int left, right, destination;
                if (!(cin >> operation >> left >> right >> destination))
                    throw runtime_error("truncated hint program");
                hint.push_back({operation, left, right, destination});
            }
            prog = ORDER_MODE == 9 ? p.polish_tail_hint(hint) : p.polish_hint(hint);
        } else {
            p.solve();
            prog = p.compile();
        }
        cout << id << " [";
        for (size_t k = 0; k < prog.size(); k++) {
            auto [op, a, b, c] = prog[k];
            if (k)
                cout << ',';
            cout << "[\"" << char(op) << "\"," << a << ',' << b << ',' << c << ']';
        }
        cout << "]\n" << flush;
    }
} catch (const exception &error) {
    cerr << "Solver error: " << error.what() << '\n';
    return 1;
}
