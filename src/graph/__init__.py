"""
The LangGraph orchestration layer. Read in this order:

    graph_state.py    what flows through the graph, and the reducer rules
    nodes.py          the twelve nodes; each says REAL, STUB or PARTIAL
    edges.py          the five routers and the topology declared as data
    support_graph.py  assembly, plus a dependency-free reference interpreter

The dependency arrow points one way: the graph knows about retrieval, routing, safety and
memory; none of them know a graph exists.
"""
