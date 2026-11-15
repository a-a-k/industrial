#include "model.hpp"
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>

// Scalar deadline task: independent topological recurrence with monotone
// availability cursors. No event heap, time grid or operation-log output.
class RiskDag {
    const Instance& in;
    std::vector<int> order, previous;
    std::vector<Tick> finish;
    std::vector<std::size_t> cursor;
public:
    explicit RiskDag(const Instance& data): in(data), previous(data.ops.size(),-1),
        finish(data.ops.size()), cursor(data.queues.size()) {
        std::vector<int> degree(in.ops.size());
        std::vector<std::vector<int>> next(in.ops.size());
        for (const auto& op:in.ops) for(int p:op.pred) { ++degree[op.id]; next[p].push_back(op.id); }
        for(const auto& queue:in.queues) for(std::size_t k=1;k<queue.size();++k) {
            previous[queue[k]]=queue[k-1]; ++degree[queue[k]]; next[queue[k-1]].push_back(queue[k]);
        }
        for(int i=0;i<static_cast<int>(degree.size());++i) if(!degree[i]) order.push_back(i);
        for(std::size_t head=0;head<order.size();++head) {
            int i=order[head];
            for(int j:next[i]) if(!--degree[j]) order.push_back(j);
        }
        if(order.size()!=in.ops.size()) throw std::runtime_error("Cyclic fixed schedule");
    }
    Tick solve(const Scenario& sc,Tick deadline) {
        std::fill(cursor.begin(),cursor.end(),0);
        Tick latest=0;
        for(int i:order) {
            const auto& op=in.ops[i];
            Tick t=std::max(op.planned,op.release);
            for(int p:op.pred) t=std::max(t,finish[p]);
            if(previous[i]>=0) t=std::max(t,finish[previous[i]]);
            auto& k=cursor[op.machine]; const auto& down=sc.down[op.machine];
            while(k<down.size() && down[k].end<=t) ++k;
            while(k<down.size() && down[k].begin<=t) { t=down[k].end; ++k; }
            Tick left=sc.work[i];
            if(t>deadline || left>deadline-t) return unknown;
            while(left>0) {
                Tick edge=k<down.size() ? std::min(deadline,down[k].begin):deadline;
                Tick take=std::min(left,edge-t); left-=take; t+=take;
                if(!left) break; // Completion exactly at a failure boundary wins.
                if(t==deadline || k==down.size()) return unknown;
                t=down[k++].end;
                if(t>deadline || left>deadline-t) return unknown;
            }
            finish[i]=t; latest=std::max(latest,t);
        }
        return latest;
    }
};

int main(int argc,char** argv) {
    try {
        if(!std::getenv("GITHUB_ACTIONS") || std::string(std::getenv("GITHUB_ACTIONS"))!="true")
            throw std::runtime_error("Actions only");
        if(argc!=5) throw std::runtime_error("risk-dag DATA SCENARIOS OUTPUT DEADLINE");
        std::ifstream df(argv[1]),sf(argv[2]); json raw,scenarios; df>>raw; sf>>scenarios;
        Instance in=read_instance(raw); RiskDag engine(in); Tick deadline=std::stoll(argv[4]);
        if(deadline<0) throw std::runtime_error("Negative deadline");
        bool trace=std::getenv("RISK_TRACE") && std::string(std::getenv("RISK_TRACE"))=="1";
        json times=json::array(); std::size_t count=0,finished=0;
        for(const auto& item:scenarios) {
            Scenario sc=read_scenario(in,item); Tick t=engine.solve(sc,deadline);
            ++count; if(t>=0) ++finished;
            if(trace) times.push_back(t<0 ? json(nullptr):json(t));
        }
        json answer={{"sample_count",count},{"finished_count",finished}};
        std::ifstream status("/proc/self/status"); std::string line;
        while(std::getline(status,line)) if(line.rfind("VmHWM:",0)==0) {
            std::istringstream value(line.substr(6)); std::uint64_t kib=0; value>>kib;
            answer["VmHWM_bytes"]=kib*1024;
        }
        if(trace) answer["finished_at"]=times;
        std::ofstream out(argv[3]); if(!out) throw std::runtime_error("Cannot write output");
        out<<answer.dump()<<'\n';
        return 0;
    } catch(const std::exception& error) { std::cerr<<error.what()<<'\n'; return 2; }
}
