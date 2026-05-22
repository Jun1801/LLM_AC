% This is samplepaper.tex, a sample chapter demonstrating the
% LLNCS macro package for Springer Computer Science proceedings;
% Version 2.21 of 2022/01/12
%
\documentclass[runningheads]{llncs}
%
\usepackage[T1]{fontenc}
% T1 fonts will be used to generate the final print and online PDFs,
% so please use T1 fonts in your manuscript whenever possible.
% Other font encondings may result in incorrect characters.
%
\usepackage{graphicx}
% Used for displaying a sample figure. If possible, figure files should
% be included in EPS format.
%
% If you use the hyperref package, please uncomment the following two lines
% to display URLs in blue roman font according to Springer's eBook style:
%\usepackage{color}
%\renewcommand\UrlFont{\color{blue}\rmfamily}
%\urlstyle{rm}
%
\usepackage{amsmath}
\usepackage{booktabs}
\begin{document}
%
\title{Beyond Thresholds: Safety-Preserving Semantic Caching in LLM-Driven Access Control}
\titlerunning{Beyond Thresholds: Semantic Caching for LLM Access Control}

\author{Tien-Dung Pham\inst{1} \and
Laurent D'Orazio\inst{2} \and
Thi-Huong-Giang Vu\inst{1} \and
Clara Bertolissi\inst{3}\and
Sébastien Hervieu\inst{4} \and
Juba Agoun\inst{5}}
%
\authorrunning{Pham et al.}
% First names are abbreviated in the running head.
% If there are more than two authors, 'et al.' is used.
%
\institute{Hanoi University of Science and Technology (HUST), Hanoi, Vietnam \\
\email{dung.pt2416680@sis.hust.edu.vn} \and Univ Rennes, CNRS, IRISA, Rennes, France \and Univ Orléans, INSA Centre Val de Loire, LIFO (UR 4022), Bourges, France \and ALTEN Group, France \and CNRS, INSA Lyon, Univ Claude Bernard Lyon 1, Univ Lumière Lyon 2, École Centrale de Lyon, LIRIS (UMR 5205), Lyon, France }
%
\maketitle              % typeset the header of the contribution
%
\begin{abstract}
Access control systems increasingly handle contextual, natural-language requests that resist expression as static rules. Large language models (LLMs) offer broader policy
coverage but introduce two problems: high per-request latency and non-deterministic outputs on semantically identical inputs. We introduce a layered access control pipeline that resolves both by placing a semantic cache backed by approximate nearest-neighbor search over request embeddings upstream of the LLM decision path.
A mandatory soft-policy re-evaluation on every cache hit prevents stale decisions from being served when security-relevant context has changed. We also propose a three-layer cache poisoning
defense and an Otsu-based adaptive threshold controller derived from the natural bimodal
structure of the access control similarity distribution. We evaluate on 202 labeled access scenarios and a 111-case cache benchmark, achieving 98.01\% decision accuracy,
0.0\% false-allow rate, and a 30$\times$ latency reduction on cache hits. An ablation
study shows that disabling re-evaluation produces a 100\% false-allow rate on near-miss
variants, and that the cache improves accuracy by 2.96~pp by stabilizing LLM outputs on
borderline policy categories. Similarity analysis further reveals that near-miss requests
score $S_{\text{cache}} \approx 1.0$ regardless of threshold, making metadata binding --- not threshold tuning the necessary defense.

\keywords{Access control  \and Large language models \and Semantic caching }
\end{abstract}

%
%
\section{Introduction}
Modern enterprise systems must control access to a growing range of sensitive resources such as reports, dashboards, audit logs, personnel data, whose appropriate use depends not only on a requester's role and clearance level, but also on transient operational context such as ongoing security incidents, time windows, or escalating sensitivity classifications. Conventional policy engines such as RBAC~\cite{sandhu1996rbac}, ABAC ~\cite{xacml2013}, and OPA/Rego~\cite{opa} offer precise, auditable enforcement over well-structured inputs, but they have no mechanism for interpreting natural language purpose fields or reasoning about contextual intent. Large language models (LLMs) can interpret such requests in a flexible, context-aware way, yet they lack the determinism and auditability that access control enforcement requires: an LLM may produce different decisions for equivalent inputs, cannot natively guarantee consistency with a defined policy, and offers no stable audit trail.

A practical access control system must also be efficient. Enterprise request traffic is structurally repetitive — the same roles request the same resource types under the same context across many sessions, thereby making it wasteful to invoke an LLM for every request independently. Embedding-based semantic caching addresses this by reusing a prior decision whenever a new request is sufficiently similar to a cached one. However, this introduces  the cache safety problem: a cached ALLOW decision that was correct at caching time may become stale if the security context has changed since the decision was stored. No existing work addresses this problem: prior semantic caching systems [CITE] reuse prior outputs without any safety re-check, and LLM-based authorization research [CITE, CITE] focuses on policy authoring or interpretation rather than runtime enforcement with safety guarantees.


\section{Related work}
\textbf{Traditional access control models.} Frameworks like RBAC~\cite{sandhu1996rbac} and ABAC~\cite{xacml2013} rely on deterministic rules that are highly auditable but require exhaustive policy authoring and struggle with natural-language requests. Our work uses OPA/Rego~\cite{opa} as a deterministic enforcement layer, delegating contextual decisions to an LLM only when static policies prove insufficient, thereby preserving auditability while extending coverage.

\noindent\textbf{LLMs as policy decision points.} Recent work explores LLMs in access control
primarily for policy authoring: Coletti et al.~\cite{coletti2024sacmat} pair LLMs with formal JML specifications to generate RBAC-compliant code, and
LACE~\cite{lace2025} translates natural-language policies into structured rules for IoT
systems. PermLLM~\cite{permllm2025} addresses a complementary problem, enforcing
access control on LLM outputs when the model itself is the data source. Our work differs in focus: we deploy an LLM on the runtime decision path, evaluating
natural-language access requests against dynamic policy context, with a semantic cache
as the primary efficiency and consistency mechanism.

\noindent\textbf{Semantic caching and its security.} GPTCache~\cite{bang2023gptcache} established embedding-based cache lookup for LLM responses; vCache~\cite{schroeder2025vcache} shows that static thresholds cannot simultaneously satisfy hit-rate and correctness requirements, proposing user-defined error guarantees instead. Our adaptive controller
(Section~3.4) addresses the same limitation via Otsu's method on the naturally bimodal
access control distribution, requiring no error-rate specification. Zhang et
al.~\cite{zhang2026cacheattack} show that semantic cache keys are locality-preserving
fuzzy hashes, enabling 86\% black-box response hijacking by crafting colliding text.
Our threat is orthogonal: near-miss requests carry \emph{identical} text with divergent
security metadata, scoring $S_{\text{cache}}\approx 1.0$ without crafting — a vector
that metadata binding (Section~3.3) closes at lookup.

\section{System Architecture}
\subsection{Pipeline Overview}
\begin{figure}
    \centering    \includegraphics[width=\linewidth, trim={0.5cm 0.5cm 0.5cm 0.5cm}, clip]{figures/mermaid-diagram-2026-05-18-100446.png}
    \caption{Layered access control pipeline. 
Requests pass through hard-policy enforcement and threat 
screening before entering the semantic cache. 
Cache lookup routes via similarity score: $s \geq T_{\text{hit}}$ 
triggers soft re-evaluation yielding \texttt{ALLOW\_CACHE}; 
$T_{\text{low}} \leq s < T_{\text{hit}}$ routes through cross-encoder 
to soft policy; misses fall through to LLM decision and OPA 
policy veto. All paths converge at \texttt{\_finalize()} for audit 
and cache update.}
    \label{fig:pipeline}
\end{figure}

Figure~\ref{fig:pipeline} illustrates three main stages in access control pipeline. An
incoming request is first normalized into a canonical form comprising the request text and a structured metadata context \{\texttt{role, clearance\_level, resource\_type, \\incident\_state, \ldots}
\}. The normalized request passes through a
deterministic hard-rule gate (OPA/Rego~\cite{opa}) that enforces structurally
unambiguous policies \{\texttt{MFA, session validity, clearance bounds, role--resource
binding}\} -- denying non-compliant requests immediately without engaging the embedding
pipeline. Requests that pass the gate are encoded by a bi-encoder and screened against a threat-pattern
store; high-similarity matches are denied as \texttt{DENY\_THREAT}. Clean requests enter
the semantic cache: a hit triggers soft-policy re-evaluation of dynamic conditions
(\texttt{incident\_state, time-window}) before returning \texttt{ALLOW\_CACHE}; a miss
invokes the LLM decision-maker (GPT-4o mini~\cite{openai2024gpt4o}), whose proposal is
subject to a deterministic OPA post-veto before the final response is written to the
immutable audit stream.

\subsection{Threshold Configuration}
Cache routing is governed by two thresholds over the cosine similarity score
$S_{\text{cache}} \in [0,1]$ computed as the cosine distance between the query embedding
and the nearest cached entry. The routing function is:

$\text{Route}(S_{\text{cache}}) = \begin{cases}
\texttt{HIT}      & \text{if } S_{\text{cache}} \geq T_{\text{hit}} \\
\texttt{NEAR-HIT} & \text{if } T_{\text{validate\_low}} \leq S_{\text{cache}} < T_{\text{hit}} \\
\texttt{MISS}     & \text{if } S_{\text{cache}} < T_{\text{validate\_low}}
\end{cases}$

\noindent\texttt{HIT} candidates proceed to soft-policy re-evaluation; \texttt{NEAR-HIT}
candidates are first re-scored by a cross-encoder~\cite{reimers2019sentence} before
re-evaluation; \texttt{MISS} requests are forwarded to the LLM. Four named presets for
$(T_{\text{hit}}, T_{\text{validate\_low}})$ are provided in Table~\ref{tab:modes};
Section~3.4 describes an adaptive controller that derives both from observed traffic.

\begin{table}[t]
\caption{Threshold presets. $T_{\text{attack}}$ governs threat-screening denial.}
\label{tab:modes}
\centering
\renewcommand{\arraystretch}{1}
\begin{tabular}{lccc}
\toprule
Mode & $T_{\text{hit}}$ & $T_{\text{validate\_low}}$ & $T_{\text{attack}}$ \\
\midrule
loose        & 0.80 & 0.60 & 0.80 \\
moderate     & 0.85 & 0.65 & 0.82 \\
balanced     & 0.90 & 0.70 & 0.85 \\
strict       & 0.95 & 0.80 & 0.80 \\
\bottomrule
\end{tabular}
\end{table}

\subsection{Cache Poisoning Defense}
The semantic cache introduces two attack vectors absent in rule-based systems. A
\emph{retrieval attack} crafts a request textually close or identical to a cached
\texttt{ALLOW} entry while altering a security-critical field such as
\texttt{incident\_state}. Figure~\ref{fig:dist} shows why threshold-based defenses are
insufficient: near-miss variants that differ from their anchor \emph{only} in metadata,
score $S_{\text{cache}} \approx 1.0$ because the request text is identical, so no
threshold calibration can separate them from legitimate repeats. An \emph{injection
attack} targets the store directly, inserting fabricated entries to redirect future
requests.

\noindent We propose three complementary layers.

\textbf{Layer 1 --- Metadata Binding. } We partition metadata into \textit{context fields}
(\texttt{role, department, region, resource\_type}), used as ANN pre-filters, and
\textit{security-critical fields} (\texttt{incident\_state, sensitivity,
clearance\_level, \\time\_window}), which must match exactly. A candidate $c$ is eligible for cache serving only if:

$\text{Eligible}(q, c) = \mathbb{1}[S_{\text{cache}}(q,c) \geq T_{\text{hit}}] \;\wedge\; \mathbb{1}[M_q = M_c]$

When $S_{\text{cache}} \geq T_{\text{hit}}$ but $M_q \neq M_c$, the request is routed to
a \texttt{SUSPICIOUS\_HIT} audit path, intercepting retrieval attacks before soft
re-evaluation is reached.

\textbf{Layer 2 --- Adversarial Probe Detection. } A probing adversary must
submit multiple near-miss variants for the same (\texttt{user\_id, resource\_type})
pair. We propose flagging sessions with repeated \texttt{SUSPICIOUS\_HIT} events or a
monotonically increasing $S_{\text{cache}}$ trend --- a signature of iterative threshold
search, routing them to \texttt{DENY\_THREAT}. False-positive evaluation is left as
future work.

\textbf{Layer 3 --- Entry Integrity. } Each cache entry is signed with an HMAC over its
security-critical fields, decision, and embedding hash; entries that fail verification
on read are quarantined and trigger an alert, closing the injection vector.

Together, the three layers implement \emph{context-bound caching}: a cached decision is
reusable only when text similarity, security-context equivalence, and entry integrity are
simultaneously satisfied.

\subsection{Adaptive Threshold Calibration}
Manual threshold selection assumes a known, stable similarity distribution — an
assumption that breaks when the embedding model or workload changes. We propose an
adaptive controller that derives both thresholds from observed traffic.

\begin{figure}
    \centering    \includegraphics[width=0.7\linewidth]{figures/similarity_distribution.png}
    \caption{Cosine similarity distribution of 87 Phase~B variants relative
to their anchor requests. Three regions are
visible: artifact-swap variants cluster in $[0.33, 0.63]$; an empty gap
spans $[0.626, 0.801]$ with no observed samples; paraphrase variants
cluster in $[0.80, 0.88]$. Near-miss variants (red, purple) score at
$S_{\text{cache}} \approx 1.0$ despite requiring different access
decisions, which demonstrate that similarity thresholds alone are
insufficient for cache safety.}
    \label{fig:dist}
\end{figure}
\noindent\textbf{Empirical distribution. } Figure~\ref{fig:dist} shows three distinct regions in
the Phase~B similarity distribution. Artifact-swap variants cluster in $[0.33,\,0.63]$
($\mu=0.47$); paraphrase variants cluster in $[0.80,\,0.88]$ ($\mu=0.85$); an empty gap
spans $[0.626,\,0.801]$ with no observed samples. Near-miss variants score at
$S_{\text{cache}}\approx 1.0$ and cannot be partitioned by any threshold (Section~3.3).

\noindent\textbf{Calibration.} The controller applies Otsu's
method~\cite{otsu1979threshold}, which selects the threshold $T^*$ that maximizes the
between-class variance of the observed $S_{\text{cache}}$ distribution:

$$\sigma^2_B(t) = w_0(t)\,w_1(t)\,[\mu_0(t) - \mu_1(t)]^2, \qquad
T^* = \arg\max_{t}\;\sigma^2_B(t),$$
where $w_k(t)$ and $\mu_k(t)$ are the weight and mean of class $k \in \{0,1\}$ at
threshold $t$. On our benchmark, $T^* = 0.626$ --- the lower boundary of the empty gap,
correctly separating the artifact-swap cluster from all higher-similarity populations.
Two operational thresholds follow:

$$T_{\text{validate\_low}} \leftarrow \mathrm{clip}\!\left(\mathrm{Otsu}(\{S_{\text{cache}}\}),\;0.65,\;0.80\right)$$
$$T_{\text{hit}} \leftarrow \mathrm{clip}\!\left(\hat{g},\;0.85,\;0.97\right),$$
where $\hat{g}$ is the minimum observed similarity among high-cluster samples (gap upper
bound). The lower bound $0.85$ on $T_{\text{hit}}$ equals the minimum observed paraphrase
similarity, ensuring no genuine paraphrase falls below the hit threshold.
$T_{\text{validate\_low}}$ sits within the empty gap, so the cross-encoder path handles
only requests with no empirical precedent, a principled definition of the near-hit
regime. The controller recomputes every $N$ requests from the audit stream and runs
asynchronously with zero latency impact.

\section{Evaluation}
\subsection{Experimental Setup}
We evaluate the pipeline along two axes: decision correctness and cache efficiency.

\noindent\textbf{Phase A --- Decision Correctness. }We construct a synthetic dataset of 202 labeled access requests covering the full policy matrix: 51 hard-deny cases (MFA failure,
session expiry, clearance violation, role–resource mismatch, unknown role), 46 soft-rule cases (critical incident, out-of-hours, elevated clearance combined with confidential
sensitivity), 105 LLM-path cases spanning four sensitivity levels and elevated-clearance
variants, and 8 near-miss boundary cases with identical prompts but different \texttt{incident\_state}. Ground-truth labels are derived offline from the OPA policy engine, ensuring independence from the system under test.

\noindent\textbf{Phase B --- Cache Benchmark. }We construct 111 anchor-variant pairs to isolate cache
behavior. Twenty-four anchor requests warm the cache, one per $(\text{role} \times \text{resource\_type})$ combination. Variants fall into four types:
\textit{paraphrase} (same request, different wording; 24 cases), \textit{artifact\_swap}
(same template, different artifact within resource type; 24 cases),
\textit{near\_miss\_incident} (identical text, \texttt{incident\_state=critical}; 24
cases), and \textit{near\_miss\_elevated\_conf} (identical text, elevated clearance with
confidential sensitivity; 15 cases).

\noindent\textbf{Evaluation metrics.} We evaluate \textit{decision correctness} via overall accuracy, reason-code accuracy, false-escalation rate (FE: over-cautious routing to human review), and crucially, false-allow rate (FA). FA serves as our primary safety metric, as misclassifying a \texttt{DENY}/\texttt{ESCALATE} as \texttt{ALLOW} grants unauthorized access. \textit{Cache performance} is measured by hit rate, decision precision on hits, and per-path latency (p50/p95 over 30 iterations).

\noindent\textbf{Models and infrastructure.} GPT-4o mini~\cite{openai2024gpt4o} serves as
the LLM decision-maker; embeddings use \texttt{all-MiniLM-L6-v2}~\cite{reimers2019sentence}
(384-dim) with Qdrant as vector store; cross-encoder re-scoring uses
\texttt{ms-marco-MiniLM-L-6-v2}. Latency benchmarks: 30 iterations,
\texttt{balanced} mode ($T_{\text{hit}}=0.90$).


\subsection{Decision Correctness (Phase A) }

Table~\ref{tab:phaseA} summarizes the results. The pipeline achieves 98.01\% overall
accuracy with a false-allow rate of 0.0\%. All 51 hard-deny cases reach 100\% accuracy
across all tested configurations. Soft-rule categories perform strongly; the two-step
chain-of-thought prompt \cite{wei2022chain}, which separates hard-rule boundary checking from
escalation-condition evaluation, is the key design decision enabling this.

\begin{table}[t]
\caption{Phase~A decision accuracy by category group (201 evaluated cases).
FA = false allow, FE = false escalate.}
\label{tab:phaseA}
\centering
\renewcommand{\arraystretch}{1} % Dãn dòng nhẹ
\begin{tabular}{lccc}
\toprule
Category group & Cases & Accuracy & Errors \\
\midrule
Hard-deny (all types)               & 51  & 100\%   & — \\
Soft-rule (critical, OOH, review)   & 46  & 100\%   & — \\
LLM-path (standard sensitivity)     & 91  & 100\%   & — \\
LLM-path (elevated + restricted)    & 7   & 85.7\%  & 1 FE \\
LLM-path (elevated + internal)      & 7   & 57.1\%  & 3 FE \\
\midrule
\textbf{Overall}                    & 202 & \textbf{98.01\%} & 4 FE, 0 FA \\
\bottomrule
\end{tabular}
\end{table}

\noindent The four remaining errors (Table~\ref{tab:phaseA}, bottom two rows) share a root cause:
the LLM conflates \texttt{sensitivity=restricted} and \texttt{sensitivity=internal} with
the S2 escalation condition, which requires \texttt{sensitivity=confidential} exactly.
Prompt design limitations are discussed in Section~5.

\subsection{Semantic Cache Benchmark (Phase B)}

\textbf{Safety properties. }Cache precision is 1.0 at every threshold tested
($T_{\text{hit}} \in \{0.80, 0.85, 0.88, 0.90, 0.93, 0.95\}$): every decision served
from cache is correct. The false-allow rate from cache is 0.0\%. This guarantee holds
because soft-policy re-evaluation is applied on every cache hit before returning
\texttt{ALLOW\_CACHE}, ensuring that stale decisions are never served when
security-relevant context has changed.

\noindent\textbf{Threshold insensitivity. }Table~\ref{tab:thresh} summarizes the threshold sweep.
Cache hit rate is flat at 27.6\% for all $T_{\text{hit}} \in [0.85, 0.95]$: the
similarity distribution (Figure~\ref{fig:dist}) contains no samples in the band
$[0.63, 0.80]$, so raising the threshold in $[0.85, 0.95]$ does not exclude any variant
type. At $T_{\text{hit}}=0.80$, hit rate rises to 35.6\% as 7 artifact-swap variants
enter the cache; precision remains 1.0 but semantic matches become more ambiguous,
supporting a recommended lower bound of $T_{\text{hit}} \geq 0.85$.

\begin{table}[t]
\centering
\renewcommand{\arraystretch}{1} % Dãn dòng nhẹ cho cả 2 bảng
\begin{minipage}{0.54\linewidth}
  \centering
  \caption{Phase~B threshold sweep. ArtSwap = artifact\_swap hit rate}
  \label{tab:thresh}
  \begin{tabular}{lcccc}
  \toprule
  Mode & $T_{\text{hit}}$ & Hit rate & Prec. & ArtSwap \\
  \midrule
  loose    & 0.80 & 0.356 & 1.0 & 0.292 \\
  moderate & 0.85 & 0.276 & 1.0 & 0.0   \\
  balanced & 0.90 & 0.276 & 1.0 & 0.0   \\
  strict   & 0.95 & 0.276 & 1.0 & 0.0   \\
  \bottomrule
  \end{tabular}
\end{minipage}
\hfill
\begin{minipage}{0.42\linewidth}
  \centering
  \caption{Latency per path (30 iter., \texttt{balanced}).}
  \label{tab:latency}
  \begin{tabular}{lcc}
  \toprule
  Path & p50 & p95 \\
  \midrule
  Cache hit  & \textbf{71} & 230   \\
  Validation & 99          & 299   \\
  LLM miss   & 2,157       & 2,923 \\
  \bottomrule
  \end{tabular}
\end{minipage}
\end{table}

\subsection{Latency}

Table~\ref{tab:latency} reports micro-benchmark results over 30 iterations per path in \texttt{balanced} mode. The cache-hit path (p50: 71 ms) is approximately 30$\times$ faster than the LLM path (p50: 2,157 ms). The cross-encoder validation path introduces only a modest overhead, bringing the total p50 latency to 99 ms, which remains well below the LLM path even at p95 (299 ms vs.\ 2,923 ms).

While our micro-benchmark measured a paraphrase hit rate of 27.6\%, enterprise access control workloads typically follow a Zipfian distribution~\cite{breslau1999zipf}. Consequently, we expect substantially higher effective hit rates in practice due to the prevalence of repeated resource requests.

\subsection{Ablation Study}

We isolate the contribution of three pipeline components by disabling each in turn while
holding all others constant. Table~\ref{tab:ablation} summarizes the results.


\noindent\textbf{A1 — Cache re-evaluation disabled. }Table~\ref{tab:a1} shows the
per-variant breakdown. Without soft re-evaluation, all 39 near-miss variants are served
the stale cached \texttt{ALLOW} decision; cache precision drops from 1.0 to 0.552.
Paraphrase and artifact-swap variants are unaffected because their security context
matches the cached entry, and only variants that change a security-critical field produce
false allows. This result establishes soft re-evaluation as a safety-critical component:
without it, the cache becomes the primary attack surface of the system.


\begin{table}[t]
\caption{A1: false-allow rate per variant type when cache re-evaluation is disabled
(Phase~B, 87 variants). Reeval ON = full pipeline.}
\label{tab:a1}
\centering
\renewcommand{\arraystretch}{1} % Dãn dòng nhẹ giúp bảng thoáng hơn
\begin{tabular}{lccc} % Cập nhật thành lccc (1 cột trái, 3 cột giữa)
\toprule
Variant type & Cases & FA (reeval ON) & FA (reeval OFF) \\
\midrule
paraphrase              & 24 & 0.0\%    & 0.0\%    \\
artifact\_swap          & 24 & 0.0\%    & 0.0\%    \\
near\_miss\_incident   & 24 & 0.0\%    & \textbf{100\%} \\
near\_miss\_elev+conf  & 15 & 0.0\%    & \textbf{100\%} \\
\midrule
\textbf{All near-miss} & \textbf{39} & \textbf{0.0\%} & \textbf{100\%} \\
\bottomrule
\end{tabular}
\end{table}

\noindent\textbf{A2 — Semantic cache disabled. }Removing the cache degrades accuracy from
98.01\% to 95.05\% ($-$2.96 pp), with the false-escalation rate doubling from 1.99\% to
4.95\%. Accuracy loss concentrates exclusively in two borderline LLM categories:
\texttt{policy\_pass\_elevated\_internal} drops from 57.1\% to 28.6\% and
\texttt{policy\_pass\_elevated\_restricted} from 85.7\% to 28.6\%. All other categories
remain at 100\%. The semantic cache, once it stores a correct LLM decision for a
borderline case, prevents stochastic LLM variation from producing a different answer on
semantically equivalent repeat requests. This establishes that the cache contributes a
measurable accuracy benefit beyond latency reduction.

\begin{table}[t]
\caption{Ablation results on Phase~A (A2, A3). FA = false allow, FE = false escalate,
RC = reason-code accuracy, LLM = LLM invocations / total cases.}
\label{tab:ablation}
\centering
\renewcommand{\arraystretch}{1} % Vẫn nên dãn hàng một chút
\setlength{\tabcolsep}{8pt}
\begin{tabular}{llccccc}
\toprule
Variant & Acc. & FA & FE & RC acc. & LLM calls \\
\midrule
Full pipeline                 & \textbf{98.01\%} & \textbf{0.0\%} & 1.99\% & 47.8\% & 129/201 \\
A2: no cache     & 95.05\% & 0.0\% & 4.95\% & 47.8\% & 130/202 \\
A3: no pre-gate  & 94.00\% & 0.0\% & 6.00\% & \textbf{23.0\%} & 179/200 \\
\bottomrule
\end{tabular}
\end{table}

\noindent\textbf{A3 — Hard-rule pre-gate disabled. }The LLM without the pre-gate achieves
94.00\% decision accuracy, indicating that it has partially internalised hard rules.
However, removing the pre-gate causes three secondary effects: reason-code accuracy
collapses from 47.8\% to 23\%, as hard-deny cases return \texttt{VETO\_}-prefixed codes
from the post-LLM veto rather than direct rule-derived codes, breaking downstream
routing on reason codes; LLM invocations increase from 129 to 179 (+37.7\%), as 72
requests no longer intercepted by the gate reach the embedding pipeline; and
\texttt{policy\_pass\_elevated\_restricted} collapses to 0\% accuracy (vs 28.6\% in A2),
indicating that the pre-gate also suppresses LLM over-escalation on borderline categories
by establishing explicit policy boundaries before LLM reasoning begins.

\section{Conclusion}
We presented a layered access control pipeline combining deterministic hard-rule
enforcement, semantic caching, and LLM-based reasoning. On 202 labeled scenarios
and an 111-case cache benchmark, the system achieves 98.01\% accuracy, 0.0\%
false-allow rate, and 30$\times$ latency reduction on cache hits. Ablation
reveals two generalizable findings: semantic caching improves accuracy by
2.96~pp by stabilizing LLM outputs on borderline categories; and cache safety
requires soft-policy re-evaluation --- not stricter thresholds because near-miss
requests score $S_{\text{cache}} \approx 1.0$ regardless of $T_{\text{hit}}$.
We further propose a three-layer cache poisoning defense and an Otsu-based
adaptive threshold controller.

\noindent\textbf{Limitations and future work.} Evaluation is limited to synthetic
scenarios under a single model pair (\texttt{all-MiniLM-L6-v2} + GPT-4o mini);
cross-model validation and production log benchmarks remain future work.
Reason-code accuracy (47.8\%) and rationale grounding (0.0\%) limit
auditability — RAG over policy documents is the likely remedy. Layer~2
(adversarial probe detection) is proposed but unevaluated; a red-team study
is needed.
%
% ---- Bibliography ----
%
% BibTeX users should specify bibliography style 'splncs04'.
% References will then be sorted and formatted in the correct style.
%
% \bibliographystyle{splncs04}
% \bibliography{mybibliography}
%
\begin{thebibliography}{15}

\bibitem{sandhu1996rbac}
Sandhu, R.S., Coyne, E.J., Feinstein, H.L., Youman, C.E.: Role-based
access control models. IEEE Computer \textbf{29}(2), 38--47 (1996).
\doi{10.1109/2.485845}

\bibitem{xacml2013}
OASIS: eXtensible Access Control Markup Language (XACML) Version~3.0.
OASIS Standard (2013). \url{https://docs.oasis-open.org/xacml/3.0}

\bibitem{coletti2024sacmat}
Coletti, A., et al.: LLM-assisted generation of RBAC policies from
natural language specifications. In: Proceedings of SACMAT.
ACM, New York (2024).

\bibitem{opa}
Open Policy Agent: OPA -- The open policy agent (2024).
\url{https://www.openpolicyagent.org}

\bibitem{lace2025}
Cheng, Y., Xu, M., Zhang, Y., Li, K., Wu, H., Zhang, Y., Guo, S.,
Qiu, W., Yu, D., Cheng, X.: Say what you mean: Natural language
access control with large language models for Internet of Things.
arXiv:2505.23835 (2025).

\bibitem{permllm2025}
Jayaraman, B., Marathe, V.J., Mozaffari, H., Shen, W.F.,
Kenthapadi, K.: Permissioned {LLM}s: Enforcing access control
in large language models. In: Advances in Neural Information
Processing Systems (NeurIPS) (2025).

\bibitem{bang2023gptcache}
Bang, Y., et al.: GPTCache: Semantic cache for LLM queries. In:
Proceedings of the 3rd Workshop for Natural Language Processing
Open Source Software (NLP-OSS), pp. 212--218. ACL (2023).

\bibitem{schroeder2025vcache}
Schroeder, T., et al.: vCache: Semantic caching with correctness
guarantees for LLM inference. arXiv:2502.03771 (2025).

\bibitem{zhang2026cacheattack}
Zhang, Z., Liu, Z., Xie, Y., Huang, Q., She, D.: From similarity
to vulnerability: Key collision attack on LLM semantic caching.
arXiv:2601.23088 (2026).

\bibitem{wu2025kvcache}
Wu, Z., et al.: Side-channel attacks on LLM key-value caches in
multi-tenant settings. In: Proceedings of NDSS (2025).

\bibitem{reimers2019sentence}
Reimers, N., Gurevych, I.: Sentence-BERT: Sentence embeddings using
siamese BERT-networks. In: Proceedings of EMNLP, pp. 3982--3992.
ACL (2019).

\bibitem{openai2024gpt4o}
OpenAI: GPT-4o system card. Technical report, OpenAI (2024).
\url{https://openai.com/index/gpt-4o-system-card}

\bibitem{breslau1999zipf}
Breslau, L., et al.: Web caching and Zipf-like distributions: 
Evidence and implications. In: Proceedings of IEEE INFOCOM (1999).

\bibitem{otsu1979threshold}
Otsu, N.: A threshold selection method from gray-level histograms.
IEEE Trans. Syst. Man Cybern. \textbf{9}(1), 62--66 (1979).
\doi{10.1109/TSMC.1979.4310076}

\bibitem{wei2022chain}
Wei, J., et al.: Chain-of-thought prompting elicits reasoning in 
large language models. In: Advances in Neural Information Processing Systems (NeurIPS) (2022).

\end{thebibliography}
\end{document}

