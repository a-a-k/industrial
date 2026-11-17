#include "model.hpp"
#include <array>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <unordered_map>

using Mask=std::uint64_t;
static Tick down_time(const std::vector<Interval>& down,Tick a,Tick b) {
    Tick total=0;for(auto v:down) total+=std::max<Tick>(0,std::min(b,v.end)-std::max(a,v.begin));return total;
}
static std::vector<std::pair<Tick,Tick>> clipped(const std::vector<Interval>& down,Tick d) {
    std::vector<std::pair<Tick,Tick>> out;
    for(auto v:down) {if(v.begin<d) out.emplace_back(v.begin,std::min(v.end,d));}
    return out;
}
struct Row {
    Scenario base,fast;Mask active=0;
    std::vector<std::array<bool,2>> bad;
    std::unordered_map<Mask,bool> cache;
};
int main(int argc,char** argv) {
    try {
        if(!std::getenv("GITHUB_ACTIONS") || std::string(std::getenv("GITHUB_ACTIONS"))!="true") throw std::runtime_error("Actions only");
        if(argc!=5) throw std::runtime_error("addressed-oracle DATA BANK ANALYSIS CACHE_LIMIT");
        std::ifstream df(argv[1]),bf(argv[2]),af(argv[3]);json raw,bank,a;df>>raw;bf>>bank;af>>a;
        Instance in=read_instance(raw);int M=in.queues.size();Tick deadline=a.at("deadline");
        if(M<1 || M>32 || raw.at("delta")!=5) throw std::runtime_error("Unsupported machine profile");
        std::vector<int> used;Mask used_mask=0;
        for(int m=0;m<M;++m) if(!in.queues[m].empty()) {used.push_back(m);used_mask|=Mask(1)<<m;}
        std::vector<Row> rows;std::size_t cache_limit=std::stoull(argv[4]),entries=0,evaluations=0,hits=0,filtered=0,queries=0;
        json active=json::array(),bad=json::array();
        for(const auto& item:bank) {
            Row r;r.base=read_scenario(in,item.at("base"));r.fast=read_scenario(in,item.at("fast"));r.bad.resize(M);
            for(int m:used) {
                if(clipped(r.base.down[m],deadline)!=clipped(r.fast.down[m],deadline)) r.active|=Mask(1)<<m;
                for(int level=0;level<2;++level) {
                    const auto& down=level ? r.fast.down[m]:r.base.down[m];
                    bool fail=deadline-down_time(down,0,deadline)<a.at("machine_work").at(m).get<Tick>();
                    for(const auto& w:a.at("windows")) if(w.at("machine")==m) {
                        Tick left=w.at("begin"),right=w.at("end"),required=w.at("required");
                        fail=fail || right-left-down_time(down,left,right)<required;
                    }
                    r.bad[m][level]=fail;
                }
            }
            active.push_back(r.active);bad.push_back(r.bad);rows.push_back(std::move(r));
        }
        auto engine=make_dag(in);
        auto evaluate=[&](Row& row,Mask mask) {
            Mask local=mask&row.active;auto known=row.cache.find(local);
            if(known!=row.cache.end()) {++hits;return known->second;}
            bool impossible=false;for(int m:used) impossible=impossible || row.bad[m][(mask>>m)&1];
            bool ok=false;
            if(impossible) ++filtered;
            else {
                Scenario sc=row.base;
                for(int m:used) if((mask>>m)&1) sc.down[m]=row.fast.down[m];
                Result result=engine->solve(sc,deadline,false,5);ok=true;
                for(int i:in.final_operations) if(result.finish[i]<0 || result.finish[i]>deadline) ok=false;
                ++evaluations;
            }
            if(entries<cache_limit) {row.cache.emplace(local,ok);++entries;}
            return ok;
        };
        std::cout<<json({{"machines",M},{"used",used},{"used_mask",used_mask},{"samples",rows.size()},
            {"active_masks",active},{"bad",bad}}).dump()<<std::endl;
        std::string line;
        while(std::getline(std::cin,line)) {
            json request=json::parse(line);
            if(request.value("stop",false)) break;
            auto started=std::chrono::steady_clock::now();Mask mask=request.at("mask").get<Mask>();
            if(mask&~used_mask) throw std::runtime_error("Unused machine selected");
            bool full=request.value("full",true);std::size_t target=request.value("target",rows.size()),good=0,fail=0;
            if(target>rows.size()) throw std::runtime_error("Invalid threshold");
            json labels=json::array();bool stopped=false;
            for(auto& row:rows) {
                if(stopped) {labels.push_back(nullptr);continue;}
                bool ok=evaluate(row,mask);labels.push_back(ok);good+=ok;fail+=!ok;
                if(!full && (good>=target || fail>rows.size()-target)) stopped=true;
            }
            ++queries;std::uint64_t peak=0;std::ifstream proc("/proc/self/status");std::string status_line;
            while(std::getline(proc,status_line)) if(status_line.rfind("VmHWM:",0)==0) peak=std::stoull(status_line.substr(6))*1024;
            std::cout<<json({{"mask",mask},{"labels",labels},{"successes",good},{"failures",fail},
                {"complete",good+fail==rows.size()},{"feasible",good>=target},{"entries",entries},
                {"dag_evaluations",evaluations},{"cache_hits",hits},{"analytic_failures",filtered},{"queries",queries},{"VmHWM_bytes",peak},
                {"wall_s",std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count()}}).dump()<<std::endl;
        }
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 2;}
}
