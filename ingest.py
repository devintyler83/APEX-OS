"""Root entry point for DraftOS ingest pipeline. Delegates to draftos.db.Ingest."""
from draftos.db.Ingest import main

if __name__ == "__main__":
    main()
