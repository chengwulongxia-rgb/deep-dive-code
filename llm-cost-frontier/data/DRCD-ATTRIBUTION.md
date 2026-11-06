# DRCD subset attribution / license

The `results/drcd-cpu/sample-manifest.json` contains a 33-question subset (including full original paragraphs and answers) redistributed from DRCD via MediaTek-Research/TCEval-v2. No original question, paragraph, answer, typo, or script variant has been corrected. Added fields: experimental split membership, source row index, and paragraph SHA-256.

- DRCD creators / upstream: DRCKnowledgeTeam / Delta Electronics, Inc.; https://github.com/DRCKnowledgeTeam/DRCD
- Pinned upstream revision: `b944790de5af02c5fbb7cd9cb1473d27d169eebf`.
- Distribution: https://huggingface.co/datasets/MediaTek-Research/TCEval-v2 at `93ae26a94572907f6d33f9844abd9d074bcc3723`, `drcd/test-00000-of-00001.parquet`.
- This DRCD subset remains **CC-BY-SA 3.0**, https://creativecommons.org/licenses/by-sa/3.0/. This notice does **not** assign a license to the entirety of TCEval-v2 or imply DRCD terms license our code or Qwen weights.
- DRCD derives its passages from Wikipedia; see upstream DRCD for original dataset organization and attribution.

## Upstream copyright notice (verbatim)

本資料集整理、改編自維基百科，其內容以CC-BY-SA 3.0條款發布。
台達電子對於本資料集內容之正確性不為任何擔保，且不就因使用或倚賴本資料集而引致的任何損失，承擔任何責任。

DRCD is compiled and adapted from Wikipedia and its content is published under the terms of CC-BY-SA 3.0. Delta Electronics, Inc. makes no representations or warranties of the correctness of the contents of DRCD and will not be liable for any loss or damage arising from the use or reliance on DRCD.

The upstream license evidence was checked in the preflight and copied here for self-contained replay. Qwen models are separately Apache-2.0 under their official pinned repositories; weights and llama.cpp binaries live only in the user cache, not Git.
