Sythetic data for semantic cache validation:
  Anchor prompt  →  "Request access to Q3 financial dashboard"
  Variant A (sim ~0.97)  →  "Need access to Q3 finance dashboard"       ← should cache-hit, same decision 
  Variant B (sim ~0.88)  →  "Retrieve the Q3 financial reports"          ← threshold boundary
  Variant C (sim ~0.80)  →  "Pull analytics on third-quarter revenue"    ← near-miss zone

  ┌───────────────────────────────────────────────────────────┬───────┬───────────────────────────────┐   
  │                         Category                          │ Count │            Purpose            │   
  ├───────────────────────────────────────────────────────────┼───────┼───────────────────────────────┤   
  │ Anchor prompts (sent first to warm cache)                 │ ~30   │ Known decisions cached        │   
  ├───────────────────────────────────────────────────────────┼───────┼───────────────────────────────┤   
  │ High-similarity variants (sim ≥ 0.93)                     │ ~30   │ Should hit, test precision    │   
  ├───────────────────────────────────────────────────────────┼───────┼───────────────────────────────┤   
  │ Medium-similarity variants (0.85–0.92)                    │ ~30   │ Threshold boundary zone       │   
  ├───────────────────────────────────────────────────────────┼───────┼───────────────────────────────┤   
  │ Near-miss variants (same prompt, different                │ ~20   │ Should miss via metadata      │   
  │ sensitivity/role)                                         │       │ filter                        │   
  └───────────────────────────────────────────────────────────┴───────┴───────────────────────────────┘   

  The near-miss variants are the most important — they test whether the metadata filter prevents a cache  
  hit when the user's role or clearance changed between the anchor and the query.

  resource_type already constrain cache hits correctly —  only
   need to vary the prompt text


  3. The near_miss_soft_allow/deny pairs already cover the        
  safety-critical boundary

  ┌────────────────────────────────┬───────┬──────────────────┐   
  │            Category            │ Count │     Purpose      │   
  ├────────────────────────────────┼───────┼──────────────────┤   
  │ Anchor prompts (sent first to  │ ~30   │ Known decisions  │   
  │ warm cache)                    │       │ cached           │   
  ├────────────────────────────────┼───────┼──────────────────┤   
  │ High-similarity variants (sim  │ ~30   │ Should hit, test │   
  │ ≥ 0.93)                        │       │  precision       │   
  ├────────────────────────────────┼───────┼──────────────────┤   
  │ Medium-similarity variants     │ ~30   │ Threshold        │   
  │ (0.85–0.92)                    │       │ boundary zone    │   
  ├────────────────────────────────┼───────┼──────────────────┤   
  │ Near-miss variants (same       │       │ Should miss via  │   
  │ prompt, different              │ ~20   │ metadata filter  │   
  │ sensitivity/role)              │       │                  │   
  └────────────────────────────────┴───────┴──────────────────┘   

The near-miss variants are the most important — they test       
  whether the metadata filter prevents a cache hit when the user's
   role or clearance changed between the anchor and the query.    
  hit when the user's role or clearance changed between the anchor and the query.




  Three ablations worth running (in order of importance):                                                 
  
  Ablation 1 — Cache without soft re-eval (most critical)

  Modify _handle_cache_hit() to skip the soft policy re-evaluation and return ALLOW_CACHE directly on any 
  embedding similarity hit. Run Phase B.

  - Expected: cache precision drops below 1.0, some near-miss variants get false-ALLOWed
  - This is the direct proof of your main architectural contribution
  - Without this comparison, a reviewer can say "the cache precision might be 1.0 anyway without the      
  re-eval"

  Ablation 2 — Hard rules + LLM, no cache

  Disable Qdrant entirely. Run Phase A for accuracy, Phase B for latency.

  - Expected: same accuracy as full system, 30× higher latency for all requests
  - Proves the cache value: efficiency gain without accuracy cost

  Ablation 3 — LLM only, no hard rules, no cache

  Bypass stages 1–4, send everything directly to the LLM. Run Phase A.

  - Expected: lower accuracy on hard-rule cases (LLM occasionally fails deterministic checks), higher     
  latency, higher cost
  - Proves the value of hard-rule gating: LLM shouldn't evaluate what OPA can decide deterministically    

  ---
  What a comparison table would look like:

  ┌───────────────────────────────────────────┬──────────┬─────────────┬─────────────┬───────────┐        
  │              System variant               │ Accuracy │ False Allow │ p50 Latency │ Cost/req  │        
  ├───────────────────────────────────────────┼──────────┼─────────────┼─────────────┼───────────┤        
  │ LLM only                                  │ ~85–90%* │   ~1–3%*    │  2,157 ms   │ $0.000069 │        
  ├───────────────────────────────────────────┼──────────┼─────────────┼─────────────┼───────────┤        
  │ Hard rules + LLM (no cache)               │  98.01%  │    0.0%     │  2,157 ms†  │ $0.000069 │        
  ├───────────────────────────────────────────┼──────────┼─────────────┼─────────────┼───────────┤        
  │ Full pipeline, cache without soft re-eval │ 98.01%*  │    >0%*     │    71 ms    │ $0.000000 │        
  ├───────────────────────────────────────────┼──────────┼─────────────┼─────────────┼───────────┤        
  │ Full pipeline (proposed)                  │  98.01%  │    0.0%     │    71 ms    │ $0.000000 │        
  └───────────────────────────────────────────┴──────────┴─────────────┴─────────────┴───────────┘        

  * predicted — needs measurement
  † hard-rule cases still fast, LLM cases at 2,157 ms

  ---
  What you do NOT need:

  - Comparison against RBAC/ABAC — they simply cannot handle natural language inputs, so the comparison is
   unfair and adds little insight
  - Comparison against external LLM-based access control systems — none are publicly available with the   
  same policy structure, making fair comparison impossible
  - Comparison against RAG-based approaches — valid idea but would take significant implementation effort 
  for a short paper; better as future work