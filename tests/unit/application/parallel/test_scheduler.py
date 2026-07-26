from pathlib import Path

from geoqc.application.parallel import TaskScheduler, WorkerPolicy


def test_scheduler_preserves_order_and_assigns_stable_sequences() -> None:
    tasks = TaskScheduler().schedule((Path("b.gpkg"), Path("a.gpkg")))

    assert [(task.sequence, task.source.name) for task in tasks] == [
        (0, "b.gpkg"),
        (1, "a.gpkg"),
    ]


def test_worker_count_respects_cpu_memory_task_and_policy_caps() -> None:
    scheduler = TaskScheduler(WorkerPolicy(maximum_workers=8, estimated_bytes_per_worker=100))

    assert scheduler.worker_count(20, cpu_count=12, available_memory=350, requested_workers=8) == 2


def test_unsafe_driver_forces_serial_fallback() -> None:
    assert TaskScheduler().worker_count(10, multiprocessing_safe=False) == 1
