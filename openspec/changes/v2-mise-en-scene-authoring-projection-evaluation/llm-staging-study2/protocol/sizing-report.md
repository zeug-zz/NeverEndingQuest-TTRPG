# Study 2 Offline Sizing and Step-(a) Packet

Status: ESTIMATE. Largest reference estimate L=1319; owner-approved max_tokens=16384, timeout_seconds=720; formula proposal remains max_tokens=6144, timeout_seconds=360.

Counts use the documented UTF-8-bytes/3 approximation, not a model tokenizer. Cost is a three-scene estimate from the hash-verified historical listing; no calls were made.

Per-scene estimates (reference bytes; reference L; request input tokens; cost USD):
- into_the_deepvault:scene:ha003-i02: 3850; 1284; 19699; 0.0101619
- into_the_deepvault:scene:sd005-i03: 3864; 1288; 16199; 0.0098119
- xhalruuns_masquerade:scene:tsu001-ao02: 3956; 1319; 17322; 0.0099242

Total ESTIMATE: $0.0298980. Rates: prompt 0.0000001 USD/token; completion 0.0000005 USD/token.
