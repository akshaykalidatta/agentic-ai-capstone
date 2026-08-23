"""
Human review.

`reviewer_actions` is the vocabulary and ships from P0, because `edges.after_review` needs to
know which action re-enters the graph. `approval_queue` and `review_service` are P7: every
decision the review surface makes lives here, and `app/streamlit_app.py` only renders.
"""
