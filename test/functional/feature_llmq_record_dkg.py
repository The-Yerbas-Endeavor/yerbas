#!/usr/bin/env python3
"""Real quorums across the cutover selected by the first signed ON record."""
from feature_llmq_release_dkg import ReleaseDKG


class RecordDKG(ReleaseDKG):
    record_selected_cutover = True


if __name__ == '__main__':
    RecordDKG().main()
