from notesman.retrieval.sparse import doc_vector, query_vector, stem, tokens


def test_stemming_joins_word_forms():
    assert len({stem(w) for w in ["scheduling", "scheduled", "schedules", "schedule"]}) == 1
    assert stem("processes") == stem("process")
    assert tokens("The CPU is scheduling the processes") == [stem("cpu"), stem("scheduling"), stem("processes")]


def test_doc_vector_sorted_and_length_normalised():
    short = doc_vector("round robin scheduling")
    long = doc_vector("round robin scheduling " + "filler words appear here " * 80)
    assert short.indices == sorted(short.indices)
    # same term, but a much longer document gets a lower BM25 weight
    term = query_vector("robin").indices[0]
    weight = lambda v: v.values[v.indices.index(term)]  # noqa: E731
    assert weight(short) > weight(long)


def test_query_vector_matches_doc_terms():
    q, d = query_vector("What is round robin scheduling?"), doc_vector("Round Robin scheduling gives a quantum")
    assert set(q.indices) <= set(d.indices) | set(q.indices)
    assert len(set(q.indices) & set(d.indices)) >= 3
