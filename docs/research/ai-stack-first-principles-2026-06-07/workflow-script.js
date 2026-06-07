export const meta = {
  name: 'ai-stack-first-principles',
  description: 'First-principles deep research + adversarial synthesis of a self-hosted Claude-Code-like AI stack for the home-ops Talos/Flux cluster',
  phases: [
    { title: 'Layer Research', detail: 'parallel deep research: one agent per stack layer, identifies purpose + OSS candidates + integration surface' },
    { title: 'Maturity Verify', detail: 'adversarially verify each finalist candidate: real maintained amd64 image, license, activity, backend deps — kill hallucinated freshness' },
    { title: 'Integration Map', detail: 'synthesize cross-layer integration matrix + identify glue/shim costs and conflicts' },
    { title: 'Adversarial Challenge', detail: 'three skeptics attack the proposed stack: over-engineering, integration-debt, cluster-fit' },
    { title: 'Final Synthesis', detail: 'reconcile into a go-forward stack determination with keep/add/replace/drop verdicts vs current' },
  ],
}

const CLUSTER = `
TARGET ENVIRONMENT (home-ops cluster — ground ALL recommendations in this):
- Platform: Talos Linux (immutable rootfs, NO DKMS, API-configured nodes), Kubernetes, FluxCD GitOps (OCIRepository + chartRef pattern preferred; bjw-s app-template for chartless apps).
- Nodes: 3x control-plane (bee-jms-0{1,2,3}, Ryzen APU Cezanne gfx90c 16GiB UMA on -03) + 1x worker bigboi-jms-01 (Ryzen 9 5950X, 32GB, AMD Navi 21 RX 6900 XT dGPU 16GB VRAM, 80CU).
- GPU reality: AMD only. Inference via Vulkan (llama.cpp/llama-swap). ROCm is NON-FUNCTIONAL on Talos (segfaults, no DKMS path) — CONFIRMED dead, do not propose ROCm. vLLM needs ROCm gfx10+ → not viable. No NVIDIA/CUDA anywhere.
- Storage: openebs-hostpath (local NVMe, RWO, node-pinned, fast) + openebs-hostpath-fast (bigboi NVMe) + nfs-client (RWX, mobile). S3 = RustFS at s3.68cc.io (NOT minio; use aws/rclone/boto3). Durability = S3 backups (Velero, CNPG Barman), NOT replication. Single-replica everywhere.
- Datastores already running: CloudNative-PG postgres18 (with pgvector ext) DB-per-app; DragonflyDB (Redis-compatible) DB-per-consumer; ClickHouse (standalone, for langfuse); Dolt (MySQL-compat). PREFER reusing these over standing up new stateful DBs. A candidate needing a NEW graph DB (Neo4j/FalkorDB) or NEW vector DB (Qdrant/Milvus) is a STRIKE against single-datastore discipline.
- Networking: Traefik Gateway API (traefik-internal VIP .17 LAN-only, traefik-external VIP .15 public via Cloudflare tunnel). Auth = Authentik forwardAuth (per-ns Middleware via Component, NOT oauth2-proxy/traefikoidc). Wildcard cert *.68cc.io.
- Constraints: memory <2Gi/pod preferred, vertical scaling, amd64 ONLY (verify multi-arch images include linux/amd64). License must be OSS (Apache/MIT/AGPL ok for self-host; flag open-core feature paywalls).

CURRENTLY DEPLOYED in ai/ namespace (the stack under review):
- LiteLLM (gateway, OpenAI-compat, litellm.68cc.io) → fans out to:
- llama-swap (local GGUF inference, Vulkan on Navi 21 dGPU, hot-swap chat models + always-on embed/rerank). Models: qwen3-1.7b/4b/14b, qwen-coder 3b/7b, embed-nomic, rerank-bge.
- Open WebUI (chat UI, ai.68cc.io). NOTE: its MEMORY_PROVIDER=mem0_server env is a DEAD no-op — current OWUI upstream has NO external memory provider concept; memory is native-only (memory table + configured vector DB).
- n8n (workflow automation). Has built-in LangChain memory sub-nodes incl Zep; mem0 only via community node.
- AnythingLLM (RAG, per-workspace pgvector). Client-only — no external shared-memory integration.
- LangFuse (LLM observability, ClickHouse+pg+dragonfly).
- owui-pipelines (model router for OWUI).
- faster-whisper (STT, Wyoming) + piper (TTS, Wyoming) → Home Assistant Assist.
- mem0 (SUSPENDED — upstream ghcr image is 404; never deployable).

USER'S STATED GOAL (the north star — evaluate every layer against THIS):
"A locally hostable Claude-Code-like toolchain from OSS, with pipelines/configs for: (1) RAG, (2) automating findings & tasks, (3) remote access from phone, (4) delegation to agents running on the homelab cluster, (5) in-cluster AMD hardware for models, with limited LiteLLM passthrough to upstream Anthropic/OpenAI."
`;

const LAYER_SCHEMA = {
  type: 'object',
  required: ['layer', 'purpose', 'candidates', 'integration_notes', 'cluster_fit', 'open_questions'],
  properties: {
    layer: { type: 'string' },
    purpose: { type: 'string', description: 'What this layer does and why it exists in a Claude-Code-like stack' },
    candidates: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'what', 'image', 'backend_deps', 'license', 'activity', 'amd64', 'fit_verdict'],
        properties: {
          name: { type: 'string' },
          what: { type: 'string' },
          image: { type: 'string', description: 'exact registry/image:tag if known, or "NONE/build-required" or "unknown-verify"' },
          backend_deps: { type: 'string', description: 'datastores/services it requires (postgres? new graph db? redis? gpu?)' },
          license: { type: 'string' },
          activity: { type: 'string', description: 'last release/commit date if known, maintenance health, any deprecation signal' },
          amd64: { type: 'string', description: 'yes/no/unknown — must verify multi-arch' },
          fit_verdict: { type: 'string', description: 'strong-fit / viable / weak / reject — with one-line reason grounded in the cluster constraints' },
        },
      },
    },
    integration_notes: { type: 'string', description: 'How candidates connect to adjacent layers (LiteLLM, OWUI, n8n, postgres). API surface (REST/MCP/OpenAI-compat). Shim costs.' },
    cluster_fit: { type: 'string', description: 'Talos/AMD/Flux/single-datastore specific concerns for this layer' },
    open_questions: { type: 'array', items: { type: 'string' }, description: 'things the maturity-verify phase must confirm' },
    recommended_primary: { type: 'string', description: 'the single best candidate for THIS cluster, or "keep current: X", or "drop layer"' },
  },
}

const LAYERS = [
  { key: 'inference-engine', prompt: `LAYER: Local model inference engine (the thing that actually runs GGUF/model weights on the AMD GPU). Current: llama-swap (llama.cpp + hot-swap, Vulkan). Research the PURPOSE of this layer and OSS candidates that run LLMs on AMD-Vulkan (NO ROCm — it's dead on Talos): llama.cpp/llama-swap, Ollama, localai, ramalama, koboldcpp, text-generation-webui backends, others. Focus: which support model hot-swapping on a single 16GB GPU, Vulkan backend, OpenAI-compat API, and an init-fetch model story. Be honest about whether llama-swap is still the right call or if something matured past it.` },
  { key: 'model-gateway', prompt: `LAYER: Model gateway / router (unifies local + cloud models behind one OpenAI-compatible endpoint, virtual keys, budgets, routing, fallback). Current: LiteLLM. Research PURPOSE and OSS candidates: LiteLLM, OpenRouter-self-host alternatives, Portkey gateway (OSS?), GPUStack, Bifrost, llama-swap's own router, Envoy AI Gateway, others. Focus: virtual keys w/ model allow-lists (kid-safe needs this), spend tracking, local+cloud fan-out, Anthropic+OpenAI passthrough, observability hooks (langfuse). Is LiteLLM still best-in-class mid-2026?` },
  { key: 'chat-ui', prompt: `LAYER: Chat UI / front-end (human conversational interface, multi-user, model picker, mobile-accessible). Current: Open WebUI. Research PURPOSE and OSS candidates: Open WebUI, LibreChat, Lobe Chat, AnythingLLM-as-chat, Jan, others. Focus: mobile/PWA access (user wants phone access), multi-user, OpenAI-compat backend (point at LiteLLM), RAG integration, tool/function calling, MCP client support, native memory. Compare OWUI vs LibreChat specifically — LibreChat has strong agent/MCP story.` },
  { key: 'rag-knowledge', prompt: `LAYER: RAG / knowledge base (document ingestion, chunking, embedding, retrieval, citations). User explicitly wants RAG. Current: AnythingLLM (per-workspace pgvector). Research PURPOSE and OSS candidates: AnythingLLM, RAGFlow, Open WebUI built-in RAG, Verba, Danswer/Onyx, Haystack, LlamaIndex-server, Quivr, Khoj. Focus: pgvector-compatible (reuse CNPG, avoid new vector DB), document connectors, reranking (we have rerank-bge), citation quality, API for other apps to query. Is a dedicated RAG app needed or does OWUI/Onyx subsume it?` },
  { key: 'agent-orchestration', prompt: `LAYER: Agent orchestration / delegation framework (the CORE of "Claude-Code-like": autonomous agents that take a task, plan, use tools, write code/files, iterate). User wants "delegation to agents on the homelab cluster". Research PURPOSE and OSS candidates for SELF-HOSTED agent runtimes that can run coding/task agents server-side: OpenHands (ex-OpenDevin), Aider (CLI), bolt.diy, SWE-agent, Goose (Block), Letta, CrewAI/AutoGen-as-service, Dify agents, n8n agents, Flowise. Focus: can it run AS A SERVICE in-cluster (not just a local CLI), take delegated tasks (API/webhook trigger), use an OpenAI-compat endpoint (LiteLLM), execute code in a sandbox, and be driven from a phone. This is the MOST important layer for the stated goal — be thorough.` },
  { key: 'coding-agent', prompt: `LAYER: Coding agent specifically (Claude-Code analog — reads repos, edits code, runs commands, opens PRs). User's north star is "Claude-Code-like". Research SELF-HOSTABLE OSS coding agents that work with local/OpenAI-compat models: OpenHands (cloud+self-host, has a Helm/docker server mode), Aider, Goose, Cline/Roo (VSCode-bound — flag if not server-side), Continue.dev (client-side), SWE-agent, Tabby (autocomplete), others. Focus: which can run headless/server-side in-cluster and be delegated to remotely vs which are IDE/CLI-only. Honest assessment: can ANY OSS coding agent driven by a local 7B-14B Vulkan model actually approximate Claude Code, or is cloud passthrough (Anthropic via LiteLLM) mandatory for usable quality?` },
  { key: 'workflow-automation', prompt: `LAYER: Workflow automation / task automation ("automate findings and tasks"). Current: n8n. Research PURPOSE and OSS candidates: n8n, Windmill, Activepieces, Huginn, Node-RED, Temporal (heavier), Dify (workflow+agents). Focus: LLM/agent nodes, webhook triggers, scheduling, calling LiteLLM, integration with the agent layer, code execution. Is n8n still the right pick or does Windmill/Dify fit a Claude-Code-like automation goal better?` },
  { key: 'memory-layer', prompt: `LAYER: Memory layer (persistent cross-conversation/cross-app memory). CONTEXT: prior research found OWUI has NO external memory provider (mem0 env is dead), Zep CE is deprecated, Letta self-host is deprecated, mem0 has no prebuilt amd64 image, Cognee needs Neo4j for multi-consumer. Candidates still standing: mem0 self-built (pgvector-only), Memobase (ghcr.io/memodb-io/memobase, postgres+redis), Redis Agent Memory Server. Research PURPOSE and RE-EXAMINE whether a dedicated memory layer is even warranted vs native app memory. Focus brutally on: maintained amd64 image, postgres/pgvector or dragonfly backend (NO new DB), REST API, and the HARD truth that every consumer needs a custom shim. Recommend whether to include this layer at all.` },
  { key: 'mcp-tooling', prompt: `LAYER: MCP server layer / tool-use infrastructure (gives agents tools: web search, code exec, file access, cluster access). Claude-Code-like agents need tools. Current: metamcp deployed in services ns. Research PURPOSE and OSS candidates: MetaMCP (aggregator), individual MCP servers, mcpo (MCP-to-OpenAPI proxy for OWUI), Toolhive, MCP gateways. Focus: how agents/OWUI/LibreChat consume MCP tools in-cluster, sandboxed code execution servers, and whether an MCP aggregator/gateway is the right pattern. Also: sandboxed code execution for agents (E2B-alternatives self-host, like open-interpreter, jupyter-kernel-gateway, microsandbox).` },
  { key: 'embeddings-rerank', prompt: `LAYER: Embeddings + reranking (vectorize text for RAG/memory, rerank retrieved chunks). Current: embed-nomic + rerank-bge via llama-swap always-on group. Research PURPOSE and whether llama-swap is the right host for embeddings or if a dedicated embedding server (infinity, text-embeddings-inference (TEI — needs which backend?), fastembed) is better on AMD-Vulkan. Focus: AMD GPU compat (Vulkan, no ROCm), OpenAI-compat /embeddings endpoint, throughput for RAG ingestion, staying resident alongside chat models on 16GB.` },
  { key: 'voice-layer', prompt: `LAYER: Voice (STT + TTS, for assistant/phone interaction). Current: faster-whisper + piper (Wyoming → Home Assistant). User wants phone access (voice is a plus). Research PURPOSE and OSS candidates: faster-whisper, whisper.cpp, piper, kokoro-tts, openedai-speech, speaches (ex-faster-whisper-server). Focus: OpenAI-compat /audio endpoints (so LiteLLM/OWUI can use them directly, not just Home Assistant), AMD/CPU viability, integration beyond Home Assistant. Is the current Wyoming-only wiring limiting?` },
  { key: 'observability', prompt: `LAYER: LLM observability / tracing / eval (trace prompts, debug agents, track cost/latency/quality). Current: LangFuse (+ClickHouse). Research PURPOSE and OSS candidates: Langfuse, Phoenix (Arize), Helicone, OpenLLMetry/Traceloop, Lunary. Focus: integration with LiteLLM (langfuse has native callback), agent-trace visibility (for the OpenHands/agent layer), self-host maturity, backend deps. Is Langfuse+ClickHouse justified or overkill?` },
  { key: 'remote-access', prompt: `LAYER: Remote/mobile access pattern ("remote access from my phone", "delegation to agents"). NOT an app but an access architecture. Current: Cloudflare tunnel + Traefik + Authentik forwardAuth, apps at *.68cc.io. Research PURPOSE and patterns: which stack components have good mobile PWA/native apps (OWUI PWA, LibreChat, etc), how to delegate a task to an in-cluster agent from a phone (chat UI → agent, or a dedicated agent inbox/API, or messaging bridge like a Telegram/Matrix bot → n8n → agent), and secure exposure. Focus on the END-TO-END "I'm on my phone, I delegate a coding/research task to my cluster, it runs and reports back" flow. What OSS pieces enable that?` },
]

phase('Layer Research')
const layerResults = await parallel(
  LAYERS.map(l => () => agent(
    `${CLUSTER}\n\nYou are researching ONE layer of this stack. Do DEEP, evidence-based research (use web search/fetch, GitHub, Docker Hub/ghcr, official docs — cite URLs, image tags, dates). Do NOT trust your training data on version freshness or image availability — that changes monthly and you WILL be wrong; flag anything you couldn't verify as "unknown-verify" so a later phase confirms it.\n\n${l.prompt}\n\nReturn structured findings. Be specific about exact image names, backend dependencies, license, and a cluster-fit verdict per candidate. For the recommended_primary, decide between keeping the current tool vs switching, and say WHY in cluster terms.`,
    { label: `research:${l.key}`, phase: 'Layer Research', schema: LAYER_SCHEMA }
  ))
)
const layers = layerResults.filter(Boolean)

const VERIFY_SCHEMA = {
  type: 'object',
  required: ['name', 'claim_checked', 'image_real', 'amd64_confirmed', 'maintained', 'backend_deps_confirmed', 'verdict'],
  properties: {
    name: { type: 'string' },
    claim_checked: { type: 'string', description: 'the specific image/maturity claim being verified' },
    image_real: { type: 'string', description: 'CONFIRMED exists / 404-DOES-NOT-EXIST / build-required / could-not-verify — with the registry URL checked' },
    amd64_confirmed: { type: 'string', description: 'yes-multiarch / arm64-only / no / could-not-verify' },
    maintained: { type: 'string', description: 'last release/commit date found + ACTIVE/STALE/DEPRECATED with any deprecation quote' },
    backend_deps_confirmed: { type: 'string', description: 'actual datastore/service requirements confirmed from docs/compose' },
    license: { type: 'string' },
    verdict: { type: 'string', description: 'GREEN (deployable as-is) / YELLOW (deployable with caveat X) / RED (do not use, reason)' },
    evidence: { type: 'array', items: { type: 'string' }, description: 'URLs / specific facts that back the verdict' },
  },
}

phase('Maturity Verify')
const finalists = []
const seen = new Set()
for (const lr of layers) {
  const pushName = (name, ctx) => {
    if (!name) return
    const key = name.toLowerCase().trim().split(/[\s(]/)[0]
    if (seen.has(key)) return
    seen.add(key)
    finalists.push({ name, layer: lr.layer, ctx })
  }
  pushName(lr.recommended_primary, lr.integration_notes)
  for (const c of (lr.candidates || [])) {
    if (/strong-fit|viable/i.test(c.fit_verdict || '')) {
      pushName(c.name, `image=${c.image} deps=${c.backend_deps} license=${c.license} activity=${c.activity} amd64=${c.amd64}`)
    }
  }
}
log(`Verifying ${finalists.length} distinct finalist candidates across all layers`)

const verified = await parallel(
  finalists.slice(0, 40).map(f => () => agent(
    `${CLUSTER}\n\nYou are an ADVERSARIAL maturity verifier. A prior research pass nominated "${f.name}" (layer: ${f.layer}) as a candidate. Context from research: ${f.ctx}\n\nYour job is to REFUTE or CONFIRM the load-bearing claims with primary-source evidence (GitHub releases page, Docker Hub/ghcr tags page, official docs, compose files). Specifically verify, by actually checking the registry/repo:\n1. Does a real, self-hostable container image exist? Check the EXACT registry path. A 404 is a RED. (We've been burned: mem0-server ghcr image is 404, Zep CE deprecated, Letta self-host deprecated — assume hype until proven.)\n2. Is it multi-arch with linux/amd64? (arm64-only = RED for this cluster.)\n3. Most recent release/commit date — is it ACTIVE (2026), STALE (>1yr), or explicitly DEPRECATED? Quote deprecation language verbatim if found.\n4. What backend datastores does it ACTUALLY require? (A new Neo4j/Qdrant/Milvus = note as a cost.)\n5. License + any open-core paywall on needed features.\n\nDefault to skepticism. If you cannot verify the image exists, say so — do NOT assume. Return the verdict GREEN/YELLOW/RED.`,
    { label: `verify:${f.name}`.slice(0, 60), phase: 'Maturity Verify', schema: VERIFY_SCHEMA }
  ))
)
const verdicts = verified.filter(Boolean)

phase('Integration Map')
const greenYellow = verdicts.filter(v => /GREEN|YELLOW/i.test(v.verdict || ''))
const verdictDigest = verdicts.map(v => `- ${v.name} [${v.verdict}] img:${v.image_real} amd64:${v.amd64_confirmed} maint:${v.maintained} deps:${v.backend_deps_confirmed}`).join('\n')
const layerDigest = layers.map(l => `### ${l.layer}\nPurpose: ${l.purpose}\nPrimary rec: ${l.recommended_primary}\nIntegration: ${l.integration_notes}`).join('\n\n')

const INTEGRATION_SCHEMA = {
  type: 'object',
  required: ['integration_matrix', 'glue_costs', 'conflicts', 'data_flow'],
  properties: {
    integration_matrix: { type: 'string', description: 'markdown table: component → component, protocol (OpenAI-compat/REST/MCP/Wyoming), native-or-shim' },
    glue_costs: { type: 'array', items: { type: 'string' }, description: 'each piece of custom code/config that must be built, with rough effort' },
    conflicts: { type: 'array', items: { type: 'string' }, description: 'layer choices that fight each other or duplicate function' },
    data_flow: { type: 'string', description: 'end-to-end trace of the 5 north-star flows: RAG, task automation, phone-delegation-to-agent, local inference, cloud passthrough' },
    new_datastores_required: { type: 'array', items: { type: 'string' } },
  },
}
const integration = await agent(
  `${CLUSTER}\n\nYou are the integration architect. Below are the per-layer recommendations and the adversarially-verified maturity verdicts. Produce a cross-layer INTEGRATION MAP for the strongest coherent stack.\n\nPER-LAYER:\n${layerDigest}\n\nVERIFIED VERDICTS:\n${verdictDigest}\n\nBuild: (1) an integration matrix showing how every chosen component connects (and whether native or needs a shim), (2) an explicit list of glue/shim costs, (3) conflicts or duplicated functions between layers, (4) an end-to-end data-flow trace for each of the 5 north-star goals. Prefer OpenAI-compat + MCP as the universal interfaces. Flag any new datastore a choice would force.`,
  { label: 'integration-map', phase: 'Integration Map', schema: INTEGRATION_SCHEMA }
)

phase('Adversarial Challenge')
const stackSoFar = `PER-LAYER RECS:\n${layerDigest}\n\nVERDICTS:\n${verdictDigest}\n\nINTEGRATION:\n${JSON.stringify(integration, null, 2)}`
const CHALLENGE_SCHEMA = {
  type: 'object',
  required: ['lens', 'strongest_objections', 'what_to_cut', 'what_to_keep', 'alternative_take'],
  properties: {
    lens: { type: 'string' },
    strongest_objections: { type: 'array', items: { type: 'string' } },
    what_to_cut: { type: 'array', items: { type: 'string' }, description: 'layers/components that are not justified by the north-star goal' },
    what_to_keep: { type: 'array', items: { type: 'string' } },
    alternative_take: { type: 'string', description: 'a materially different stack shape worth considering' },
  },
}
const LENSES = [
  { key: 'over-engineering', prompt: `LENS: Over-engineering / YAGNI. Attack the stack for layers that exist for completeness rather than the stated goal. The user wants a Claude-Code-like toolchain: RAG, task automation, phone delegation, local inference, cloud passthrough. Which layers are infra-for-an-architecture-diagram? Is the memory layer justified? Is a dedicated RAG app needed if OWUI/Onyx has RAG? Is Langfuse+ClickHouse overkill? Push hard for the SIMPLEST stack that hits all 5 goals.` },
  { key: 'integration-debt', prompt: `LENS: Integration debt / maintenance burden. Attack the stack for the cumulative cost of shims, glue, custom images, and version-churn across N services on a solo-operated homelab. Every self-built image (mem0) and every shim (OWUI memory) is forever-maintenance. Which choices create the most ongoing toil? Which trade a one-time setup for perpetual breakage? Favor maintained upstream images and native integrations brutally.` },
  { key: 'goal-fit', prompt: `LENS: Goal-fit / does-it-actually-work. Attack the stack on whether it DELIVERS the Claude-Code-like experience. Hard truth check: can OSS coding agents (OpenHands/Goose/Aider) driven by a 7-14B Vulkan-on-AMD model actually do useful autonomous coding, or is the local-inference goal fundamentally limited and cloud passthrough mandatory for the agent layer? Is the "delegate from phone to in-cluster agent" flow real with these tools or aspirational? Where will the user be disappointed?` },
]
const challenges = await parallel(
  LENSES.map(L => () => agent(
    `${CLUSTER}\n\nYou are a rigorous skeptic. Attack this proposed stack from your assigned lens. Be specific and constructive — name components, cut what isn't earned, but acknowledge what genuinely must stay.\n\nLENS: ${L.prompt}\n\nPROPOSED STACK:\n${stackSoFar}`,
    { label: `challenge:${L.key}`, phase: 'Adversarial Challenge', schema: CHALLENGE_SCHEMA }
  ))
)
const challengeResults = challenges.filter(Boolean)

phase('Final Synthesis')
const FINAL_SCHEMA = {
  type: 'object',
  required: ['executive_summary', 'layer_verdicts', 'recommended_stack', 'changes_vs_current', 'phased_rollout', 'honest_limitations', 'open_decisions'],
  properties: {
    executive_summary: { type: 'string', description: '3-5 sentence bottom line: is the current stack right, and the biggest changes' },
    layer_verdicts: {
      type: 'array',
      items: {
        type: 'object',
        required: ['layer', 'choice', 'verdict', 'why'],
        properties: {
          layer: { type: 'string' },
          choice: { type: 'string', description: 'the recommended component for this layer' },
          verdict: { type: 'string', description: 'KEEP / ADD / REPLACE (from X) / DROP' },
          why: { type: 'string' },
        },
      },
    },
    recommended_stack: { type: 'string', description: 'the full proposed stack as a layered diagram/description' },
    changes_vs_current: { type: 'array', items: { type: 'string' }, description: 'concrete diffs from what is deployed today' },
    phased_rollout: { type: 'array', items: { type: 'string' }, description: 'ordered phases to get from current → target, lowest-risk-first' },
    honest_limitations: { type: 'array', items: { type: 'string' }, description: 'where this stack will fall short of real Claude Code, stated plainly' },
    open_decisions: { type: 'array', items: { type: 'string' }, description: 'decisions that need the user, framed as choices' },
  },
}
const final = await agent(
  `${CLUSTER}\n\nYou are the lead architect making the final call. Reconcile all inputs into a go-forward determination for this AI stack. Be decisive but honest. Where the adversarial skeptics landed a real hit, cut the layer. Where the user's goal genuinely needs something, keep/add it. Ground every verdict in cluster constraints (AMD-Vulkan-only, Talos-no-ROCm, single-datastore, solo-operator, amd64).\n\nApply the INDEPENDENT-THOUGHT principle: do not rubber-stamp the current stack OR the most elaborate option — recommend what actually serves the stated goal with the least maintenance.\n\nPER-LAYER RESEARCH:\n${layerDigest}\n\nVERIFIED VERDICTS:\n${verdictDigest}\n\nINTEGRATION MAP:\n${JSON.stringify(integration, null, 2)}\n\nADVERSARIAL CHALLENGES:\n${JSON.stringify(challengeResults, null, 2)}\n\nProduce the final determination: per-layer KEEP/ADD/REPLACE/DROP verdicts, the recommended go-forward stack, concrete changes vs the currently-deployed stack, a lowest-risk-first phased rollout, honest limitations (especially re: local-model coding-agent quality), and the open decisions that need the user.`,
  { label: 'final-synthesis', phase: 'Final Synthesis', schema: FINAL_SCHEMA }
)

return {
  layers_researched: layers.length,
  candidates_verified: verdicts.length,
  green_yellow_count: greenYellow.length,
  integration,
  challenges: challengeResults,
  final,
}
