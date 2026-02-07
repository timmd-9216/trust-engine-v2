"""Services for NLP corpus and candidate analysis.

Provides:
- Entity mentions (NER) and counts
- Adjectives associated to each entity/candidate
- Top accounts by negative/disinformation activity
- Clusters of related accounts
- Word/adjective clusters per candidate
"""

import logging
import os
from collections import Counter
from typing import Any

from trust_api.nlp.models import (
    AccountCluster,
    AdjectivesByEntity,
    CorpusAnalysisResult,
    EntityMention,
    TopNegativeAccount,
    WordClusterByCandidate,
)

logger = logging.getLogger(__name__)

# Lazy-loaded Stanza pipelines for corpus analysis
_nlp_with_ner = None
_nlp_pos_only = None


def _stanza_device_kwargs() -> dict:
    """Build use_gpu/device kwargs for Stanza Pipeline (CUDA or Apple Silicon MPS)."""
    kwargs: dict = {}
    use_gpu = os.getenv("STANZA_USE_GPU", "").strip().lower() in ("1", "true", "yes")
    device = os.getenv("STANZA_DEVICE", "").strip() or None
    if device:
        kwargs["device"] = device
        logger.info("Stanza: using device=%s", device)
    elif use_gpu:
        try:
            import torch

            if torch.cuda.is_available():
                kwargs["use_gpu"] = True
                logger.info("Stanza: using GPU (CUDA available)")
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                kwargs["device"] = "mps"
                logger.info("Stanza: using GPU (Apple Silicon MPS)")
        except ImportError:
            pass
    if not kwargs and use_gpu:
        kwargs["use_gpu"] = True
    return kwargs


def _get_nlp_with_ner():
    """Get or create Stanza pipeline with NER (tokenize, pos, ner) for Spanish."""
    global _nlp_with_ner
    if _nlp_with_ner is not None:
        return _nlp_with_ner
    try:
        import stanza

        resources_dir = os.getenv("STANZA_RESOURCES_DIR") or os.path.join(
            os.getcwd(), "stanza_resources"
        )
        lang = os.getenv("STANZA_LANG", "es")
        stanza.download(lang, verbose=False, model_dir=resources_dir)
        device_kw = _stanza_device_kwargs()
        _nlp_with_ner = stanza.Pipeline(
            lang=lang,
            processors="tokenize,pos,ner",
            verbose=False,
            dir=resources_dir,
            **device_kw,
        )
        return _nlp_with_ner
    except Exception as e:
        logger.warning("Stanza NER pipeline not available: %s", e)
        return None


def _get_nlp_pos():
    """Get or create Stanza pipeline with tokenize+pos only (no NER)."""
    global _nlp_pos_only
    if _nlp_pos_only is not None:
        return _nlp_pos_only
    nlp_ner = _get_nlp_with_ner()
    if nlp_ner is not None:
        _nlp_pos_only = nlp_ner
        return _nlp_pos_only
    try:
        import stanza

        resources_dir = os.getenv("STANZA_RESOURCES_DIR") or os.path.join(
            os.getcwd(), "stanza_resources"
        )
        lang = os.getenv("STANZA_LANG", "es")
        stanza.download(lang, verbose=False, model_dir=resources_dir)
        device_kw = _stanza_device_kwargs()
        _nlp_pos_only = stanza.Pipeline(
            lang=lang,
            processors="tokenize,pos",
            verbose=False,
            dir=resources_dir,
            **device_kw,
        )
        return _nlp_pos_only
    except Exception as e:
        logger.warning("Stanza POS pipeline not available: %s", e)
        return None


def _post_text(post: dict[str, Any]) -> str:
    """Extract text from a post dict."""
    return str(post.get("full_text") or post.get("text") or post.get("body") or "").strip()


def _post_account(post: dict[str, Any]) -> str:
    """Extract account id/screen name from a post dict."""
    user = post.get("user") or {}
    if isinstance(user, dict):
        acc = user.get("screen_name") or user.get("username") or user.get("id_str") or ""
    else:
        acc = ""
    return str(
        acc or post.get("user_screen_name") or post.get("author") or post.get("account_id") or ""
    ).strip()


def _post_candidate(post: dict[str, Any]) -> str:
    """Extract candidate_id from a post dict."""
    return str(post.get("candidate_id") or "").strip()


def _iter_batches(items: list, batch_size: int):
    """Yield consecutive slices of items of length batch_size (last chunk may be smaller)."""
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


# --- Entity mentions (NER) ---


def get_entity_mentions(
    texts: list[str],
    *,
    batch_size: int = 32,
) -> list[EntityMention]:
    """
    Extract named entities from a list of texts and return mention counts.

    Uses Stanza NER when available; otherwise returns empty list.
    Processes texts in batches of batch_size for memory and progress control.
    """
    nlp = _get_nlp_with_ner()
    if nlp is None:
        return []

    counter: Counter[tuple[str, str]] = Counter()
    total = len([t for t in texts if t.strip()])
    processed = 0
    for batch in _iter_batches([t for t in texts if t.strip()], batch_size):
        for text in batch:
            try:
                doc = nlp(text)
                for ent in doc.ents:
                    key = (ent.text.strip(), ent.type)
                    if key[0]:
                        counter[key] += 1
            except Exception as e:
                logger.debug("Stanza NER failed for a text: %s", e)
            processed += 1
        if total > batch_size:
            logger.info("Entity mentions: processed %d / %d texts", processed, total)

    return [
        EntityMention(text=text, type=etype, count=count)
        for (text, etype), count in counter.most_common()
    ]


# --- Adjectives associated to each entity ---


def get_adjectives_by_entity(
    texts: list[str],
    candidate_entities: list[str] | None = None,
    *,
    window_tokens: int = 10,
    batch_size: int = 32,
) -> list[AdjectivesByEntity]:
    """
    For each entity (or candidate name), collect adjectives that appear near it.

    If candidate_entities is None, uses Stanza NER to find PER entities and
    collects adjectives per entity. Otherwise uses the given list of names
    (case-insensitive match in text) and collects adjectives within
    window_tokens of each mention.
    """
    # NER needed when not using candidate_entities; otherwise POS is enough
    nlp = (
        _get_nlp_with_ner()
        if candidate_entities is None
        else (_get_nlp_with_ner() or _get_nlp_pos())
    )
    if nlp is None:
        return []

    # entity -> Counter(adjective)
    adj_by_entity: dict[str, Counter[str]] = {}
    valid_texts = [t for t in texts if t.strip()]
    total = len(valid_texts)

    def add_adj(entity: str, adj: str) -> None:
        entity = entity.strip()
        adj = adj.strip().lower()
        if not entity or not adj:
            return
        if entity not in adj_by_entity:
            adj_by_entity[entity] = Counter()
        adj_by_entity[entity][adj] += 1

    processed = 0
    for batch in _iter_batches(valid_texts, batch_size):
        for text in batch:
            try:
                doc = nlp(text)
                words_with_pos = []
                for sent in doc.sentences:
                    for w in sent.words:
                        words_with_pos.append((w.text, w.upos))
                if candidate_entities:
                    entities_in_text = []
                    text_lower = text.lower()
                    for cand in candidate_entities:
                        if cand and cand.lower() in text_lower:
                            entities_in_text.append(cand)
                    if not entities_in_text:
                        processed += 1
                        continue
                    for ent in entities_in_text:
                        for word, pos in words_with_pos:
                            if pos == "ADJ":
                                add_adj(ent, word)
                else:
                    for sent in doc.sentences:
                        sent_words = [(w.text, w.upos) for w in sent.words]
                        adj_words = [w for w, pos in sent_words if pos == "ADJ"]
                        for ent in sent.ents:
                            if ent.type in ("PER", "PERSON"):
                                for a in adj_words:
                                    add_adj(ent.text, a)
            except Exception as e:
                logger.debug("Adjectives-by-entity failed for a text: %s", e)
            processed += 1
        if total > batch_size:
            logger.info("Adjectives by entity: processed %d / %d texts", processed, total)

    return [
        AdjectivesByEntity(
            entity=entity,
            adjectives=list(counts.keys()),
            counts=dict(counts),
        )
        for entity, counts in sorted(adj_by_entity.items())
    ]


# --- Top accounts by negative / disinformation activity ---


def get_top_negative_accounts(
    posts: list[dict[str, Any]],
    *,
    top_k: int = 50,
    negativity_weight_adjective_ratio: float = 0.5,
    batch_size: int = 32,
) -> list[TopNegativeAccount]:
    """
    Rank accounts by a simple negativity score: more adjectives and volume yield higher score.

    Uses adjective ratio per post as a proxy for "calificación negativa" / subjective content.
    Complements the trust-engine article metric (get_adjective_count), which uses OpenRouter/LLM
    to filter qualitative adjectives for a single article; here we use raw ratio for corpus scale.
    """
    nlp = _get_nlp_with_ner() or _get_nlp_pos()
    if nlp is None:
        return []

    account_scores: dict[str, list[float]] = {}
    valid_posts = [p for p in posts if _post_text(p).strip() and (_post_account(p) or "unknown")]
    total = len(valid_posts)
    processed = 0

    for batch in _iter_batches(valid_posts, batch_size):
        for post in batch:
            text = _post_text(post)
            acc = _post_account(post) or "unknown"
            try:
                doc = nlp(text)
                total_w = 0
                adjs = 0
                for sent in doc.sentences:
                    for w in sent.words:
                        total_w += 1
                        if w.upos == "ADJ":
                            adjs += 1
                ratio = adjs / total_w if total_w else 0.0
                if acc not in account_scores:
                    account_scores[acc] = []
                account_scores[acc].append(ratio)
            except Exception as e:
                logger.debug("Score post failed: %s", e)
            processed += 1
        if total > batch_size:
            logger.info("Top negative accounts: processed %d / %d posts", processed, total)

    # Aggregate: average ratio * post_count as score (more posts with high ratio = more negative)
    result = []
    for acc, ratios in account_scores.items():
        avg = sum(ratios) / len(ratios) if ratios else 0
        score = avg * negativity_weight_adjective_ratio * len(ratios)
        result.append(
            TopNegativeAccount(
                account_id=acc,
                score=round(score, 4),
                post_count=len(ratios),
                extra={"avg_adjective_ratio": round(avg, 4)},
            )
        )
    result.sort(key=lambda x: (-x.score, -x.post_count))
    return result[:top_k]


# --- Account clusters (related operating accounts) ---


def get_account_clusters(
    posts: list[dict[str, Any]],
    *,
    min_shared_tokens: int = 3,
    min_cluster_size: int = 2,
) -> list[AccountCluster]:
    """
    Cluster accounts that share vocabulary (e.g. same hashtags, same wording).

    Uses simple Jaccard similarity on token sets: accounts with enough
    token overlap are in the same cluster (connected components).
    """
    from collections import defaultdict

    # account -> set of tokens (lowercased words)
    account_tokens: dict[str, set[str]] = defaultdict(set)
    for post in posts:
        text = _post_text(post)
        acc = _post_account(post)
        if not acc:
            acc = "unknown"
        tokens = {t.lower() for t in text.split() if len(t) > 1}
        account_tokens[acc].update(tokens)

    # Build graph: two accounts connected if Jaccard similarity high enough
    # (or shared tokens >= min_shared_tokens)
    accounts = list(account_tokens.keys())
    n = len(accounts)
    parent = {a: a for a in accounts}

    def find(x: str) -> str:
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a: str, b: str) -> None:
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pa] = pb

    for i in range(n):
        for j in range(i + 1, n):
            a, b = accounts[i], accounts[j]
            inter = len(account_tokens[a] & account_tokens[b])
            if inter >= min_shared_tokens:
                union(a, b)

    # Group by root
    clusters: dict[str, list[str]] = defaultdict(list)
    for a in accounts:
        root = find(a)
        clusters[root].append(a)

    return [
        AccountCluster(accounts=sorted(members), size=len(members))
        for members in clusters.values()
        if len(members) >= min_cluster_size
    ]


# --- Word / adjective clusters per candidate ---


def get_word_clusters_by_candidate(
    posts: list[dict[str, Any]],
    *,
    batch_size: int = 32,
) -> list[WordClusterByCandidate]:
    """
    For each candidate_id, collect words and adjectives from their associated
    posts and return counts (cluster of terms per candidate).
    """
    nlp = _get_nlp_with_ner() or _get_nlp_pos()
    if nlp is None:
        return []

    candidate_words: dict[str, Counter[str]] = {}
    candidate_adjs: dict[str, Counter[str]] = {}
    valid_posts = [p for p in posts if _post_candidate(p) and _post_text(p).strip()]
    total = len(valid_posts)
    processed = 0

    for batch in _iter_batches(valid_posts, batch_size):
        for post in batch:
            cid = _post_candidate(post)
            text = _post_text(post)
            if cid not in candidate_words:
                candidate_words[cid] = Counter()
                candidate_adjs[cid] = Counter()
            try:
                doc = nlp(text)
                for sent in doc.sentences:
                    for w in sent.words:
                        t = w.text.strip().lower()
                        if len(t) > 1:
                            candidate_words[cid][t] += 1
                        if w.upos == "ADJ":
                            candidate_adjs[cid][t] += 1
            except Exception as e:
                logger.debug("Word cluster post failed: %s", e)
            processed += 1
        if total > batch_size:
            logger.info(
                "Word clusters by candidate: processed %d / %d posts",
                processed,
                total,
            )

    result = []
    for cid in sorted(candidate_words.keys()):
        words = candidate_words[cid]
        adjs = candidate_adjs.get(cid, Counter())
        # Merge counts for "cluster" representation
        all_counts = dict(words)
        for k, v in adjs.items():
            all_counts[k] = all_counts.get(k, 0) + v
        result.append(
            WordClusterByCandidate(
                candidate_id=cid,
                words=[w for w, _ in words.most_common(100)],
                adjectives=[a for a, _ in adjs.most_common(50)],
                counts=all_counts,
            )
        )
    return result


# --- Full corpus analysis ---


def run_corpus_analysis(
    posts: list[dict[str, Any]],
    candidate_entities: list[str] | None = None,
    *,
    top_negative_k: int = 50,
    batch_size: int = 32,
) -> CorpusAnalysisResult:
    """
    Run all NLP analyses on a corpus of posts and return a single result.

    Posts should have at least: text (full_text/text/body), optional author
    (user_screen_name/author/user), optional candidate_id.
    Always processes in batches of batch_size (default 32) and logs progress.
    """
    texts = [_post_text(p) for p in posts]
    texts = [t for t in texts if t.strip()]

    entity_mentions = get_entity_mentions(texts, batch_size=batch_size)
    adjectives_by_entity = get_adjectives_by_entity(
        texts,
        candidate_entities=candidate_entities,
        batch_size=batch_size,
    )
    top_negative_accounts = get_top_negative_accounts(
        posts,
        top_k=top_negative_k,
        batch_size=batch_size,
    )
    account_clusters = get_account_clusters(posts)
    word_clusters_by_candidate = get_word_clusters_by_candidate(
        posts,
        batch_size=batch_size,
    )

    return CorpusAnalysisResult(
        entity_mentions=entity_mentions,
        adjectives_by_entity=adjectives_by_entity,
        top_negative_accounts=top_negative_accounts,
        account_clusters=account_clusters,
        word_clusters_by_candidate=word_clusters_by_candidate,
    )
