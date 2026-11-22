// Boolean recipe selection with lazy cycle cuts. Arithmetic is replayed in Python.
#include <z3++.h>
#include <chrono>
#include <functional>
#include <iostream>
#include <string>
#include <vector>
int main() {
    int n,m,t,budget,timeout;
    if (!(std::cin>>n>>m>>t>>budget>>timeout) || n<0 || m<0 || t<0) return 2;
    std::vector<int> targets(t),out(m),left(m),right(m);
    for (int &v:targets) std::cin>>v;
    for (int i=0;i<m;i++) std::cin>>out[i]>>left[i]>>right[i];
    if (!std::cin) return 2;
    try {
        z3::context c;
        z3::solver s(c);
        z3::expr_vector used(c),chosen(c);
        for (int i=0;i<n;i++) used.push_back(c.bool_const(("v"+std::to_string(i)).c_str()));
        std::vector<std::vector<int>> groups(n);
        for (int i=0;i<m;i++) {
            if(out[i]<0 || out[i]>=n || left[i]>=n || right[i]>=n) return 2;
            chosen.push_back(c.bool_const(("r"+std::to_string(i)).c_str()));
            groups[out[i]].push_back(i);
            s.add(z3::implies(chosen[i],used[out[i]]));
            for (int a:{left[i],right[i]}) if(a>=0) s.add(z3::implies(chosen[i],used[a]));
        }
        for(int i=0;i<n;i++) {
            z3::expr_vector opts(c);
            for(int j:groups[i]) opts.push_back(chosen[j]);
            if(opts.empty()) s.add(!used[i]);
            else {
                s.add(z3::implies(used[i],z3::mk_or(opts)));
                if(opts.size()>1) s.add(z3::atmost(opts,1));
            }
        }
        for(int v:targets) {if(v<0 || v>=n)return 2;s.add(used[v]);}
        if(n) s.add(z3::atmost(used,budget));
        auto start=std::chrono::steady_clock::now();
        std::vector<int> best;
        int cuts=0,checks=0;
        while(true) {
            int elapsed=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count();
            if(elapsed>=timeout)break;
            z3::params p(c);p.set("timeout",unsigned(timeout-elapsed));s.set(p);
            auto status=s.check();checks++;
            if(status!=z3::sat)break;
            auto model=s.get_model();
            std::vector<int> recipe(n,-1),selected;
            for(int i=0;i<m;i++) if(model.eval(chosen[i],true).is_true()) {recipe[out[i]]=i;selected.push_back(i);}
            std::vector<int> color(n),stack;
            bool cyclic=false;
            std::function<void(int)> visit=[&](int v) {
                if(v<0 || color[v]==2)return;
                if(color[v]==1) {
                    z3::expr_vector cycle(c);
                    bool include=false;
                    for(int a:stack) {include|=a==v;if(include)cycle.push_back(!chosen[recipe[a]]);}
                    s.add(z3::mk_or(cycle));cyclic=true;cuts++;return;
                }
                if(recipe[v]<0)throw std::runtime_error("missing recipe");
                color[v]=1;stack.push_back(v);
                visit(left[recipe[v]]);visit(right[recipe[v]]);
                stack.pop_back();color[v]=2;
            };
            for(int v=0;v<n;v++)if(recipe[v]>=0)visit(v);
            if(cyclic)continue;
            best=std::move(selected);
            if(best.empty())break;
            s.add(z3::atmost(used,unsigned(best.size()-1)));
        }
        if(best.empty())std::cout<<"no_model\n";
        else {
            std::cout<<"sat "<<best.size()<<"\n";
            for(int i:best)std::cout<<i<<' ';
            std::cout<<'\n';
        }
        std::cerr<<"checks "<<checks<<" cycle_cuts "<<cuts<<'\n';
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
