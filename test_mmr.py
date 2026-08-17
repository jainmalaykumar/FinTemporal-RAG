import numpy as np
from langchain_community.vectorstores.utils import maximal_marginal_relevance

query_emb = np.array([0.1, 0.2])
doc_embs = [[0.1, 0.2], [0.1, 0.25], [0.9, 0.8]]
mmr_selected = maximal_marginal_relevance(query_emb, doc_embs, lambda_mult=0.7, k=2)
print(mmr_selected)
