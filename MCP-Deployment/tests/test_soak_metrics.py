"""Unit coverage for bounded OCI staging process-tree metrics."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/soak_metrics.py"
spec = importlib.util.spec_from_file_location("smoke_soak_metrics", SCRIPT)
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


def proc_stat(pid, parent, utime=20, stime=5, rss=2, name="name (nested)"):
    # fields 3..24: state, ppid, pgrp, session, tty_nr, tpgid,
    # flags, minflt, cminflt, majflt, cmajflt, utime, stime,
    # cutime, cstime, priority, nice, num_threads, itrealvalue,
    # starttime, vsize, rss
    values = ["S", str(parent)] + ["0"] * 9 + [
        str(utime), str(stime)
    ] + ["0"] * 8 + [str(rss)]
    assert len(values) == 22, len(values)
    return f"{pid} ({name}) " + " ".join(values)


class SoakMetricsTests(unittest.TestCase):
    def test_process_name_with_parentheses(self):
        pid, ppid, ticks, rss = metrics.parse_proc_stat(
            proc_stat(1234, 999, utime=17, stime=9, rss=5))
        self.assertEqual((pid, ppid, ticks), (1234, 999, 26))
        self.assertEqual(rss, 5 * metrics.PAGE_BYTES)

    def test_tree_includes_descendants_but_not_unrelated_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for pid, parent, rss in (
                (100, 1, 2), (101, 100, 3), (102, 101, 4),
                (777, 1, 80),
            ):
                (root / str(pid)).mkdir()
                (root / str(pid) / "stat").write_text(
                    proc_stat(pid, parent, rss=rss)
                )
            stats = metrics.sample_tree(100, root)
            self.assertEqual(stats["processes"], 3)
            self.assertEqual(
                stats["rss_mib"], round(9 * metrics.PAGE_BYTES / 1048576, 1))
            self.assertEqual(stats["cpu_ticks"], 75)
            self.assertEqual(metrics.sample_tree(99, root)["processes"], 0)

    def test_available_memory_and_cpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = Path(tmp) / "meminfo"
            info.write_text("MemTotal: 16384 kB\nMemAvailable: 2048 kB\n")
            self.assertEqual(metrics.available_memory_mib(info), 2.0)
        self.assertEqual(metrics.process_cpu_percent(0, metrics.CLOCK_TICKS, 1), 100.0)
        with self.assertRaises(ValueError):
            metrics.process_cpu_percent(0, 1, 0)


if __name__ == "__main__":
    unittest.main()
