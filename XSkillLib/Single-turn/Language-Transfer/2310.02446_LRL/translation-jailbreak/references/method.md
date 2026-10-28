# Method

The attack is a translation wrapper around an unsafe English instruction. The
paper translates each AdvBench instruction from English into a target language,
queries `gpt-4-0613` with greedy decoding, back-translates the model response to
English, and labels the result.

The tested languages are Zulu, Scots Gaelic, Hmong, Guarani, Ukrainian,
Bengali, Thai, Hebrew, Simplified Mandarin Chinese, Modern Standard Arabic,
Italian, Hindi, plus the untranslated English baseline. The paper groups them
into LRL, MRL, and HRL buckets and reports a combined attack as successful when
any language in the bucket bypasses for that input.

The local script implements that control flow with pluggable translation. The
default `tagged` translator is only a runnable stand-in. A faithful
machine-translation run should use `--translator project-api
--translation-provider google`, which calls the vendored helper at
`tools/translation_api.py`, or a durable cache produced by that same provider.
