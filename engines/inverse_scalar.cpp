#include "model.hpp"
#include <chrono>
#include <cstdlib>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <sys/resource.h>

static Tick down_time(const std::vector<Interval>& down,Tick a,Tick b) {
    Tick total=0;
    for(const auto& x:down) total+=std::max<Tick>(0,std::min(b,x.end)-std::max(a,x.begin));
    return total;
}

int main(int argc,char** argv) {
    try {
        if(!std::getenv("GITHUB_ACTIONS") || std::string(std::getenv("GITHUB_ACTIONS"))!="true")
            throw std::runtime_error("Actions only");
        if(argc!=7) throw std::runtime_error("inverse-scalar ENGINE DATA SCENARIOS OUTPUT DEADLINE ANALYSIS");
        auto begin=std::chrono::steady_clock::now();
        std::ifstream df(argv[2]),sf(argv[3]),af(argv[6]);json raw,histories,analysis;df>>raw;sf>>histories;af>>analysis;
        Instance in=read_instance(raw);Tick deadline=std::stoll(argv[5]);
        if(deadline!=analysis.at("deadline") || deadline<0 || raw.at("delta")!=5)
            throw std::runtime_error("Deadline/profile mismatch");
        std::string name=argv[1];std::unique_ptr<Engine> engine;
        if(name=="des") engine=make_des(in);else if(name=="dag") engine=make_dag(in);
        else throw std::runtime_error("Unknown independent engine");
        json times=json::array(),sufficient=json::array(),necessary=json::array();
        std::vector<std::size_t> window_counts(analysis.at("windows").size());
        std::size_t successes=0,capacity_count=0,necessary_count=0,sufficient_count=0,shared_count=0;
        for(const auto& item:histories) {
            Scenario sc=read_scenario(in,item);Result r=engine->solve(sc,deadline,false,5);
            for(const auto& o:in.ops) if(sc.work[o.id]!=o.work) throw std::runtime_error("Unregistered work override");
            // External product accounting: every mandatory terminal must issue by d.
            bool issued=true;Tick last=0;
            for(int terminal:in.final_operations) {
                Tick t=r.finish.at(terminal);if(t<0 || t>deadline) issued=false;else last=std::max(last,t);
            }
            bool capacity_failure=false,window_failure=false;std::vector<Interval> combined;
            for(std::size_t m=0;m<in.queues.size();++m) {
                Tick work=analysis.at("machine_work").at(m).get<Tick>();
                if(deadline-down_time(sc.down[m],0,deadline)<work) capacity_failure=true;
                if(work>0) for(const auto& v:sc.down[m]) {
                    Tick a=std::max<Tick>(0,v.begin),b=std::min(deadline,v.end);
                    if(a<b) combined.push_back({a,b});
                }
            }
            for(std::size_t k=0;k<window_counts.size();++k) {
                const auto& w=analysis.at("windows").at(k);Tick a=w.at("begin"),b=w.at("end"),required=w.at("required");
                int m=w.at("machine");
                if(b-a-down_time(sc.down.at(m),a,b)<required) { ++window_counts[k];window_failure=true; }
            }
            std::sort(combined.begin(),combined.end(),[](auto a,auto b){return a.begin<b.begin;});
            Tick union_down=0,left=0,right=0;
            for(const auto& v:combined) {
                if(v.begin>right) { union_down+=right-left;left=v.begin;right=v.end; }
                else right=std::max(right,v.end);
            }
            union_down+=right-left;
            bool guaranteed=deadline-union_down>=analysis.at("nominal").get<Tick>();
            bool impossible=capacity_failure || window_failure;
            if((impossible && issued) || (guaranteed && !issued)) throw std::runtime_error("Analytic certificate contradicts independent production");
            if(item.value("shared_calendar",false)) {
                ++shared_count;
                if(issued!=guaranteed) throw std::runtime_error("Common-calendar exact condition mismatch");
            }
            successes+=issued;capacity_count+=capacity_failure;necessary_count+=impossible;sufficient_count+=guaranteed;
            times.push_back(issued ? json(last):json(nullptr));sufficient.push_back(guaranteed);necessary.push_back(impossible);
        }
        rusage usage{};getrusage(RUSAGE_SELF,&usage);
        std::ifstream status("/proc/self/status");std::string line;std::uint64_t high_water=0;
        while(std::getline(status,line)) if(line.rfind("VmHWM:",0)==0) {
            std::istringstream value(line.substr(6));std::uint64_t kib=0;value>>kib;high_water=kib*1024;
        }
        if(!high_water) throw std::runtime_error("Post-exec VmHWM unavailable");
        json answer={{"sample_count",histories.size()},{"finished_count",successes},{"finished_at",times},
            {"necessary_failure",necessary},{"sufficient_success",sufficient},{"capacity_failure_count",capacity_count},
            {"necessary_failure_count",necessary_count},{"sufficient_success_count",sufficient_count},
            {"window_failure_counts",window_counts},{"shared_exact_checks",shared_count},{"engine",name},
            {"analytic_mismatches",0},{"VmHWM_bytes",high_water},
            {"cpu_s",usage.ru_utime.tv_sec+usage.ru_utime.tv_usec/1e6+usage.ru_stime.tv_sec+usage.ru_stime.tv_usec/1e6},
            {"wall_s",std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count()}};
        std::ofstream out(argv[4]);if(!out) throw std::runtime_error("Cannot save scalar production census");out<<answer.dump()<<'\n';
        return 0;
    } catch(const std::exception& error) {
        std::fprintf(stderr,"%s\n",error.what());return 2;
    }
}
