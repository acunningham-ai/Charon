# OWASP → MITRE ATLAS crosswalk

Two-layer provenance for every security finding: **OWASP says what kind of weakness it is;
ATLAS says what an adversary actually does with it.** A finding tagged `LLM01` tells a
reviewer it is prompt injection. The same finding tagged `AML.T0051.001` tells them it is
the *indirect* variety — arriving through content the system ingested rather than through
the prompt — which is a different fix and a different detection.

- **Source:** [`mitre-atlas/atlas-data`](https://github.com/mitre-atlas/atlas-data) → `dist/ATLAS.yaml`
- **ATLAS version:** **5.6.0** — 16 tactics, 170 techniques
  (including sub-techniques), 35 mitigations
- **Retrieved:** 2026-08-05
- **Machine-readable snapshot:** `07-References/atlas-technique-index.json`

Every ID below was validated against that snapshot when this file was generated, and
deterministic check **D32** re-validates on every run. That check exists for one reason:
a plausible-looking technique ID is the easiest thing in a security report to invent, and
the hardest for a reader to falsify. An unverifiable citation is worse than none — it
borrows authority it has not earned.

## OWASP Top 10 for LLM Applications → ATLAS

| OWASP | Weakness | ATLAS techniques |
|---|---|---|
| **LLM01** | Prompt injection | `AML.T0051` LLM Prompt Injection · `AML.T0051.000` Direct · `AML.T0051.001` Indirect · `AML.T0068` LLM Prompt Obfuscation · `AML.T0093` Prompt Infiltration via Public-Facing Application · `AML.T0061` LLM Prompt Self-Replication · `AML.T0094` Delay Execution of LLM Instructions |
| **LLM02** | Sensitive info disclosure | `AML.T0057` LLM Data Leakage · `AML.T0024` Exfiltration via AI Inference API · `AML.T0055` Unsecured Credentials · `AML.T0098` AI Agent Tool Credential Harvesting · `AML.T0082` RAG Credential Harvesting |
| **LLM03** | Supply chain | `AML.T0010` AI Supply Chain Compromise · `AML.T0010.001` AI Software · `AML.T0010.005` AI Agent Tool · `AML.T0104` Publish Poisoned AI Agent Tool · `AML.T0109` AI Supply Chain Rug Pull · `AML.T0111` AI Supply Chain Reputation Inflation · `AML.T0058` Publish Poisoned Models |
| **LLM04** | Data and model poisoning | `AML.T0020` Poison Training Data · `AML.T0019` Publish Poisoned Datasets · `AML.T0059` Erode Dataset Integrity · `AML.T0070` RAG Poisoning · `AML.T0018` Manipulate AI Model · `AML.T0031` Erode AI Model Integrity |
| **LLM05** | Improper output handling | `AML.T0077` LLM Response Rendering · `AML.T0067` LLM Trusted Output Components Manipulation · `AML.T0102` Generate Malicious Commands · `AML.T0050` Command and Scripting Interpreter |
| **LLM06** | Excessive agency | `AML.T0053` AI Agent Tool Invocation · `AML.T0086` Exfiltration via AI Agent Tool Invocation · `AML.T0101` Data Destruction via AI Agent Tool Invocation |
| **LLM07** | System prompt leakage | `AML.T0056` Extract LLM System Prompt · `AML.T0069` Discover LLM System Information |
| **LLM08** | Vector + embedding weaknesses | `AML.T0070` RAG Poisoning · `AML.T0071` False RAG Entry Injection · `AML.T0064` Gather RAG-Indexed Targets · `AML.T0066` Retrieval Content Crafting · `AML.T0082` RAG Credential Harvesting |
| **LLM09** | Misinformation | `AML.T0062` Discover LLM Hallucinations · `AML.T0060` Publish Hallucinated Entities · `AML.T0088` Generate Deepfakes |
| **LLM10** | Unbounded consumption | `AML.T0029` Denial of AI Service · `AML.T0034` Cost Harvesting · `AML.T0034.002` Agentic Resource Consumption · `AML.T0046` Spamming AI System with Chaff Data |

## OWASP Agentic AI (ASI) → ATLAS

| OWASP | Weakness | ATLAS techniques |
|---|---|---|
| **ASI01** | Goal hijack | `AML.T0051` LLM Prompt Injection · `AML.T0054` LLM Jailbreak · `AML.T0080` AI Agent Context Poisoning · `AML.T0100` AI Agent Clickbait |
| **ASI02** | Tool misuse | `AML.T0053` AI Agent Tool Invocation · `AML.T0086` Exfiltration via AI Agent Tool Invocation · `AML.T0101` Data Destruction via AI Agent Tool Invocation · `AML.T0110` AI Agent Tool Poisoning · `AML.T0099` AI Agent Tool Data Poisoning |
| **ASI03** | Identity & privilege abuse | `AML.T0012` Valid Accounts · `AML.T0073` Impersonation · `AML.T0091` Use Alternate Authentication Material · `AML.T0083` Credentials from AI Agent Configuration · `AML.T0106` Exploitation for Credential Access · `AML.T0090` OS Credential Dumping |
| **ASI04** | Supply chain | `AML.T0010` AI Supply Chain Compromise · `AML.T0010.005` AI Agent Tool · `AML.T0104` Publish Poisoned AI Agent Tool · `AML.T0109` AI Supply Chain Rug Pull · `AML.T0111` AI Supply Chain Reputation Inflation · `AML.T0011.002` Poisoned AI Agent Tool |
| **ASI05** | Code execution | `AML.T0050` Command and Scripting Interpreter · `AML.T0072` Reverse Shell · `AML.T0105` Escape to Host · `AML.T0097` Virtualization/Sandbox Evasion · `AML.T0112` Machine Compromise · `AML.T0102` Generate Malicious Commands |
| **ASI06** | Memory poisoning | `AML.T0080` AI Agent Context Poisoning · `AML.T0092` Manipulate User LLM Chat History · `AML.T0070` RAG Poisoning · `AML.T0099` AI Agent Tool Data Poisoning |
| **ASI07** | Inter-agent comms | `AML.T0103` Deploy AI Agent · `AML.T0108` AI Agent · `AML.T0061` LLM Prompt Self-Replication |
| **ASI08** | Cascading failures | `AML.T0061` LLM Prompt Self-Replication · `AML.T0031` Erode AI Model Integrity · `AML.T0048` External Harms |
| **ASI09** | Human-agent trust | `AML.T0100` AI Agent Clickbait · `AML.T0074` Masquerading · `AML.T0088` Generate Deepfakes · `AML.T0052` Phishing · `AML.T0067` LLM Trusted Output Components Manipulation |
| **ASI10** | Rogue agents | `AML.T0103` Deploy AI Agent · `AML.T0112.000` Local AI Agent · `AML.T0081` Modify AI Agent Configuration · `AML.T0084` Discover AI Agent Configuration |

## How to use it

Tag a finding with **both**: `LLM01 · AML.T0051.001`. The OWASP category groups the report;
the ATLAS technique names the adversary behaviour.

**Do not force a tag.** The mapping is not a bijection — several OWASP categories share
techniques (`AML.T0070` RAG Poisoning serves LLM04, LLM08 and ASI06, because poisoning a
retrieval store *is* all three at once), and some ATLAS techniques have no OWASP home.
Where nothing in the row fits the finding you actually have, **cite the OWASP category
alone and say the ATLAS mapping is unclear** rather than reaching for the nearest ID.

## Maintenance

ATLAS ships new techniques regularly — the agent-specific set (`AML.T0080`, `AML.T0098`–
`AML.T0112`) largely postdates the original LLM-era entries. Refresh by re-running the
generator against `dist/ATLAS.yaml`; D32 fails if the crosswalk cites an ID absent from the
snapshot, so a stale mapping surfaces rather than rotting quietly. Bumping the snapshot
without re-reading the new techniques is how a crosswalk becomes decoration.
