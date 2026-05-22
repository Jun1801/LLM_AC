- Build policy, more rules
- Verify the answers
- Check the decision by LLMs on accuracy because the hit time bias the benchmarks
  1. Threshold sensitivity sweep (already planned, highest priority)                                         Run phase B at t_hit ∈ {0.80, 0.85, 0.90, 0.93, 0.95}. Plot cache hit rate vs. accuracy. This gives the  
  empirical Pareto curve — the core contribution for "how to choose a safe threshold."                     

  2. LLM model comparison
  Your current model scores 16.7% on critical incidents — that's a model quality problem, not an
  architecture problem. Run phase A eval against a stronger model (GPT-4o or Claude). This separates       
  "architecture ceiling" from "current model floor" and makes a much stronger paper.

  3. Latency + cost combined analysis
  You already have the numbers: cache hit = 71ms, LLM miss = 2137ms (30x speedup), cache precision = 1.0,  
  false-allow = 0%. Frame this as: "semantic cache achieves 30x latency reduction and near-zero marginal   
  LLM cost for cached requests, with no safety regression." This is your main practical contribution.      

  4. Ablation study
  Three configurations to compare on the same 202-case dataset:

  ┌──────────────────────────────────┬───────────────────┬──────────────┬──────┐
  │              Config              │ Decision accuracy │ p50 latency  │ Cost │
  ├──────────────────────────────────┼───────────────────┼──────────────┼──────┤
  │ Hard rules only                  │ ?                 │ fast         │ $0   │
  ├──────────────────────────────────┼───────────────────┼──────────────┼──────┤
  │ Hard + LLM (no cache)            │ baseline          │ ~2100ms      │ high │
  ├──────────────────────────────────┼───────────────────┼──────────────┼──────┤
  │ Hard + Cache + LLM (full system) │ same              │ ~71ms cached │ low  │
  └──────────────────────────────────┴───────────────────┴──────────────┴──────┘

  This shows each component's contribution and is standard for ML papers.

  5. Fix the remaining phase A gaps
  Three categories still weak:
  - soft_deny_critical 71.4% → directly linked to the LLM quality issue in finding #2
  - policy_pass_public 87.5% → investigate the 3 false denies in the per-case CSV
  - near_miss_soft_deny 75% → 1 false allow worth examining

- bn roles, bn types, examples
- cosine simlarity vs cosine distance
- phase C
- table 3 4 5-> gộp lại được không? Chúng phải fit với objectives của phase B: 2 mục chính mà 3 bảng?

- biến trong bản 5
- arkiv

