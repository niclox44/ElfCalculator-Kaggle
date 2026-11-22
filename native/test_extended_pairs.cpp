#define NO_MAIN
#include "elfopt_extended.cpp"
#include <cassert>

int main() {
    rng.seed(130000);
    for(int trial=0;trial<24;trial++) {
        vector<u64> pool={1009+u64(trial)*2,1013+u64(trial)*6,10007,20011,101,211,37};
        Searcher s;s.setPool(pool,1000000000000000000ULL);
        u64 helper=pool[0]+pool[1];
        int budget=5;
        if(trial%2) {helper*=pool[6];budget=6;}
        u64 t1=helper*pool[2]+pool[4],t2=helper*pool[3]+pool[5];
        vector<Step> steps;
        int count=s.findPairDeep(t1,t2,budget,steps);
        assert(count>=0 && count<=budget && count==int(steps.size()));
        set<u64> available(pool.begin(),pool.end());
        for(auto st:steps) {
            assert(available.count(st.a) && available.count(st.b));
            u64 value;
            assert(ap(st.op,st.a,st.b,s.L,value) && value==st.r);
            available.insert(value);
        }
        assert(available.count(t1) && available.count(t2));
    }
    cout<<"24 shared-helper pair constructions passed exact replay\n";
}
