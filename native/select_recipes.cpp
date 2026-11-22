// Select an acyclic shared arithmetic DAG from an explicit recipe catalogue.
// Arithmetic itself is checked independently by the Python validator.
#include <z3++.h>
#include <iostream>
#include <vector>
#include <string>

int main() {
    unsigned n, m, t, budget, timeout;
    if (!(std::cin >> n >> m >> t >> budget >> timeout)) return 2;
    std::vector<int> targets(t), result(m), left(m), right(m);
    for (auto &v: targets) std::cin >> v;
    for (unsigned i=0; i<m; ++i) std::cin >> result[i] >> left[i] >> right[i];
    if (!std::cin) return 2;
    try {
        z3::context ctx;
        z3::optimize solver(ctx);
        z3::params params(ctx);
        params.set("timeout", timeout);
        solver.set(params);
        z3::expr_vector used(ctx), rank(ctx), chosen(ctx), terms(ctx);
        for (unsigned i=0; i<n; ++i) {
            used.push_back(ctx.bool_const(("u"+std::to_string(i)).c_str()));
            rank.push_back(ctx.int_const(("d"+std::to_string(i)).c_str()));
            terms.push_back(z3::ite(used[i],ctx.int_val(1),ctx.int_val(0)));
            solver.add(rank[i]>=0 && rank[i]<=static_cast<int>(n));
        }
        std::vector<std::vector<unsigned>> groups(n);
        for (unsigned i=0; i<m; ++i) {
            if (result[i]<0 || result[i]>=static_cast<int>(n) || left[i]>=static_cast<int>(n) || right[i]>=static_cast<int>(n)) return 2;
            chosen.push_back(ctx.bool_const(("r"+std::to_string(i)).c_str()));
            groups[result[i]].push_back(i);
            for (int a: {left[i],right[i]}) if (a>=0) {
                solver.add(z3::implies(chosen[i],used[a]));
                solver.add(z3::implies(chosen[i],rank[result[i]]>rank[a]));
            }
        }
        for (unsigned i=0; i<n; ++i) {
            z3::expr_vector options(ctx);
            for (auto j: groups[i]) options.push_back(z3::ite(chosen[j],ctx.int_val(1),ctx.int_val(0)));
            if (options.empty()) solver.add(!used[i]);
            else solver.add(z3::sum(options)==z3::ite(used[i],ctx.int_val(1),ctx.int_val(0)));
        }
        for (auto target: targets) {
            if (target<0 || target>=static_cast<int>(n)) return 2;
            solver.add(used[target]);
        }
        z3::expr cost=terms.empty()?ctx.int_val(0):z3::sum(terms);
        solver.add(cost<=static_cast<int>(budget));
        solver.minimize(cost);
        auto status=solver.check();
        if (status==z3::unsat) {std::cout<<"unsat\n";return 0;}
        auto model=solver.get_model();
        std::vector<unsigned> selected;
        for (unsigned i=0;i<m;++i) if (model.eval(chosen[i],true).is_true()) selected.push_back(i);
        std::cout<<(status==z3::sat?"sat":"unknown")<<" "<<selected.size()<<"\n";
        for (auto i:selected) std::cout<<i<<" ";
        std::cout<<"\n";
    } catch (const z3::exception &e) {
        std::cout<<"no_model\n";
        std::cerr<<e.msg()<<"\n";
    }
}
