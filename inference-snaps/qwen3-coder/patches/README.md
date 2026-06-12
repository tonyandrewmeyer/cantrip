# llama.cpp patches carried by this snap

The `llamacpp*` components are normally taken prebuilt from
[`canonical/llama.cpp-builds`](https://github.com/canonical/llama.cpp-builds)
releases (vanilla upstream tags, no patch mechanism). The patches in this
directory are fixes we currently need on top of upstream `b9050`
(commit `3980e04d5`); they were diagnosed against the
`qwen3-coder-tonyandrewmeyer` deployment on tam-canonical-3 in June 2026.
See `canonical-work-queue/roadmap/26.10/ai-charms/skills-iter/
PI-TOOLCALL-INVESTIGATION-LOG.md` for the full investigation.

## qwen3-coder-toolcall-and-wake-fixes.patch

Two independent fixes, both verified end-to-end (pi probe and opencode
probe both pass against a patched server; sleep→wake cycle no longer
crashes):

1. **Tool-call opener tolerance** (`common/chat-auto-parser-generator.cpp`)
   Qwen3-Coder intermittently omits the `<tool_call>` opener and starts a
   tool call directly with `<function=...>` (greedy knife-edge: flips with
   tiny prompt changes). The differential autoparser's generated parser
   and lazy grammar only recognised calls starting with `<tool_call>`, so
   such replies were passed through as plain `message.content` — OpenAI
   clients that rely on structured `tool_calls` (pi) never saw a tool
   call. The patch makes the per-call opener optional, stops pre-tool
   content at either marker, and adds `<function=` as a second
   lazy-grammar trigger. Scope-gated to tag-with-tagged-args formats with
   no section marker and a distinct tag-shaped function prefix.

2. **Sleep→wake reload crash** (`tools/server/server-context.cpp`)
   With `--sleep-idle-seconds`, every wake reloaded the model via
   `load_model(params_base)`, but `params_base.tensor_buft_overrides` had
   been written by the first load's `common_fit_params` pass and
   referenced backend state destroyed on sleep. The re-run fit aborted
   ("tensor_buft_overrides already set by user") and the subsequent load
   segfaulted; systemd restarted the service on every wake (restart
   counter reached 32 in production). The patch snapshots the launch
   params at first load and reloads from a pristine copy, so the fit
   re-runs cleanly against current free VRAM.

Both issues exist upstream as of 2026-06-12 (checked `master`); the
patch is written against `3980e04d5` and should be upstreamed.

## Prebuilt component

`qwen3-coder-tonyandrewmeyer+llamacpp-cuda_b9050-qwen3fix1.comp` (in the
snap source root, not committed to git) is the b9050 CUDA component with
the patched `bin/llama-server` and `lib/libllama-common.so*` swapped in
(built at `3980e04d5` with `-D GGML_BACKEND_DL=ON -D BUILD_SHARED_LIBS=ON`,
RPATHs stripped; all other libraries are the original artifacts). Install:

```bash
sudo snap install --dangerous \
  qwen3-coder-tonyandrewmeyer+llamacpp-cuda_b9050-qwen3fix1.comp
sudo snap restart qwen3-coder-tonyandrewmeyer.server
```

To rebuild from scratch instead: check out llama.cpp at `3980e04d5`,
`git am` the patch, build with the llama.cpp-builds workflow flags
(`-D GGML_NATIVE=OFF -D GGML_BACKEND_DL=ON -D GGML_CPU_ALL_VARIANTS=ON
-D GGML_CUDA=ON ...`), and repack the component.
