"""Phase 72.1: indexed charm-ecosystem documentation (``@docs``).

Crawls the canonical Canonical doc surfaces (Juju, ops, charmcraft,
rockcraft, jubilant, charmlibs), chunks the HTML, embeds
each chunk via the Phase 72.3 :class:`~cantrip.llm.roles.RoleRouter`,
and stores the vectors in a per-site SQLite cache under
``~/.cache/cantrip/docs-index/<site-name>/``.

Retrieval surfaces:

* :class:`~cantrip.agent.tools.docs_search.DocsSearchTool` — an
  agent-invokable tool that returns ``{site, url, excerpt, score}``
  tuples so every citation is traceable.
* :class:`~cantrip.agent.context_providers_builtin.DocsProvider` —
  the ``@docs <site> <query>`` mention surface from Phase 72.2.

The package intentionally does *not* depend on ``sqlite-vec`` or
``faiss``: similarity search runs as pure-Python cosine over the
stored vectors.  Charm-ecosystem doc corpora are small enough that
this stays sub-100ms on a laptop; swap in a native vector store
behind :class:`DocsStore` if the corpus outgrows that.
"""
