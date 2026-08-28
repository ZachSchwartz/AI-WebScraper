"""Utilities shared by the producer, scorer, database, and web services.

A regular package rather than a namespace one: every service imports these as
`util.<module>`, and without this file the type checker sees the same source
under two module names and refuses to check anything.
"""
