"""
Case history, keyed by customer. Not chat history.

Within-ticket memory needs no module: it is `Ticket.conversation_history` plus
`Ticket.transcript()`. `customer_thread_store` exists in P0 because `audit_log` writes to it on
every ticket, and the four escalating threads break silently if it is bolted on later.
"""
