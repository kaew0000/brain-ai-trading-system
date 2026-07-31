"""Two interchangeable change-detection strategies behind one
`Watcher` interface. Neither watcher reads the file's content into a
domain shape — that's a `Reader`'s job. A watcher only answers
'has this changed since I last checked?'."""
