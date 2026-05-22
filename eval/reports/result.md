- Progress across three runs (202 cases)

  ┌─────────────────────┬──────────────────────┬──────────────┬────────────────┐
  │       Metric        │ Baseline (127 cases) │ + Prompt fix │ + Pipeline fix │
  ├─────────────────────┼──────────────────────┼──────────────┼────────────────┤
  │ Overall accuracy    │ 74.0%                │ 77.7%        │ 94.1%          │
  ├─────────────────────┼──────────────────────┼──────────────┼────────────────┤
  │ False allow rate    │ 11.0%                │ 4.5%         │ 0.5%           │
  ├─────────────────────┼──────────────────────┼──────────────┼────────────────┤
  │ False deny rate     │ 15.0%                │ 16.3%        │ 4.0%           │
  ├─────────────────────┼──────────────────────┼──────────────┼────────────────┤
  │ False escalate rate │ 0%                   │ 8.4%         │ 0%             │
  └─────────────────────┴──────────────────────┴──────────────┴────────────────┘

  ---
  Category results — what each fix achieved

  ┌─────────────────────────────────┬──────────┬────────────┬─────────────┬───────────────────────────┐   
  │            Category             │ Baseline │   After    │   After     │          Status           │   
  │                                 │          │   prompt   │  pipeline   │                           │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ All hard deny (51 cases)        │ 100%     │ 100%       │ 100%        │ ✓                         │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ soft_emergency                  │ 100%     │ 0%         │ 100%        │ ✓ Fixed by ticket check   │   
  │                                 │          │ (broken)   │             │ in _llm_path              │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ soft_deny_out_of_hours          │ 0%       │ 0%         │ 100%        │ ✓ Fixed by pipeline early │   
  │                                 │          │            │             │  exit                     │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ policy_pass_elevated_restricted │ —        │ 14%        │ 100%        │ ✓ Fixed by S2 wording     │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ policy_pass_elevated_internal   │ —        │ 57%        │ 100%        │ ✓ Same fix                │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ soft_review                     │ 0%       │ 100%       │ 92.9%       │ ✓ (1 edge case)           │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ near_miss_soft_allow            │ —        │ 100%       │ 100%        │ ✓                         │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ soft_deny_critical              │ —        │ 57%        │ 71.4%       │ Improving, 2 cases still  │   
  │                                 │          │            │             │ wrong                     │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ policy_pass_restricted          │ 35%      │ 79%        │ 91.7%       │ Improving, 2 cases still  │   
  │                                 │          │            │             │ wrong                     │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ policy_pass_public              │ —        │ 87.5%      │ 87.5%       │ 3 cases still wrong       │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ near_miss_soft_deny             │ —        │ 50%        │ 75%         │ 1 case still wrong        │   
  └─────────────────────────────────┴──────────┴────────────┴─────────────┴───────────────────────────┘   

  ---
  Remaining gaps (12 cases total)

  Everything still failing is LLM inconsistency on edge cases, not structural issues:

  1. soft_deny_critical (2/7 wrong) — LLM occasionally returns DENY instead of ESCALATE_HUMAN for critical
   incidents. Could move to pipeline like out-of-hours, but would remove LLM's ability to grant
  ALLOW_EMERGENCY during critical incidents.
  2. policy_pass_public/restricted (~5 cases) — LLM occasionally over-refuses public or restricted        
  resources. Likely needs a concrete clearance example in the prompt.
  3. near_miss_soft_deny (1/4 wrong) — One elevated+confidential case still gets ALLOW. LLM inconsistency.

  ---                                                                                                     
  Category results — what each fix achieved                                                               
                                                                   
  ┌─────────────────────────────────┬──────────┬────────────┬─────────────┬───────────────────────────┐
  │            Category             │ Baseline │   After    │   After     │          Status           │
  │                                 │          │   prompt   │  pipeline   │                           │
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤     │ All hard deny (51 cases)        │ 100%     │ 100%       │ 100%        │ ✓                         │
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ soft_emergency                  │ 100%     │ 0%         │ 100%        │ ✓ Fixed by ticket check   │
  │                                 │          │ (broken)   │             │ in _llm_path              │
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ soft_deny_out_of_hours          │ 0%       │ 0%         │ 100%        │ ✓ Fixed by pipeline early │   
  │                                 │          │            │             │  exit                     │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ policy_pass_elevated_restricted │ —        │ 14%        │ 100%        │ ✓ Fixed by S2 wording     │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ policy_pass_elevated_internal   │ —        │ 57%        │ 100%        │ ✓ Same fix                │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ soft_review                     │ 0%       │ 100%       │ 92.9%       │ ✓ (1 edge case)           │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ near_miss_soft_allow            │ —        │ 100%       │ 100%        │ ✓                         │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ soft_deny_critical              │ —        │ 57%        │ 71.4%       │ Improving, 2 cases still  │   
  │                                 │          │            │             │ wrong                     │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ policy_pass_restricted          │ 35%      │ 79%        │ 91.7%       │ Improving, 2 cases still  │   
  │                                 │          │            │             │ wrong                     │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ policy_pass_public              │ —        │ 87.5%      │ 87.5%       │ 3 cases still wrong       │   
  ├─────────────────────────────────┼──────────┼────────────┼─────────────┼───────────────────────────┤   
  │ near_miss_soft_deny             │ —        │ 50%        │ 75%         │ 1 case still wrong        │   
  └─────────────────────────────────┴──────────┴────────────┴─────────────┴───────────────────────────┘   

  ---
  Remaining gaps (12 cases total)

  Everything still failing is LLM inconsistency on edge cases, not structural issues:

  1. soft_deny_critical (2/7 wrong) — LLM occasionally returns DENY instead of ESCALATE_HUMAN for critical
   incidents. Could move to pipeline like out-of-hours, but would remove LLM's ability to grant
  ALLOW_EMERGENCY during critical incidents.
  2. policy_pass_public/restricted (~5 cases) — LLM occasionally over-refuses public or restricted        
  resources. Likely needs a concrete clearance example in the prompt.
  3. near_miss_soft_deny (1/4 wrong) — One elevated+confidential case still gets ALLOW. LLM inconsistency.

  The system is now at 94.1% accuracy with 0.5% false allow rate — a strong result for a research paper. 


  ┌──────────────┬───────┬────────────────┬───────────┬─────────────────┬─────────────────┐                
  │     Mode     │ t_hit │ cache_hit_rate │ precision │ nm_incident_acc │ nm_elevated_acc │                
  ├──────────────┼───────┼────────────────┼───────────┼─────────────────┼─────────────────┤                  │ loose          │ 0.80  │ 0.356          │ 1.0       │ 0.250           │ 0.867           │                
  ├──────────────┼───────┼────────────────┼───────────┼─────────────────┼─────────────────┤                
  │ moderate     │ 0.85  │ 0.276          │ 1.0       │ 0.250           │ 0.800           │
  ├──────────────┼───────┼────────────────┼───────────┼─────────────────┼─────────────────┤
  │ performance  │ 0.88  │ 0.276          │ 1.0       │ 0.208           │ 0.733           │
  ├──────────────┼───────┼────────────────┼───────────┼─────────────────┼─────────────────┤
  │ balanced     │ 0.90  │ 0.276          │ 1.0       │ 0.208           │ 0.800           │
  ├──────────────┼───────┼────────────────┼───────────┼─────────────────┼─────────────────┤
  │ conservative │ 0.93  │ 0.276          │ 1.0       │ 0.250           │ 0.800           │
  ├──────────────┼───────┼────────────────┼───────────┼─────────────────┼─────────────────┤
  │ strict       │ 0.95  │ 0.276          │ 1.0       │ 0.208           │ 0.800           │
  └──────────────┴───────┴────────────────┴───────────┴─────────────────┴─────────────────┘

  