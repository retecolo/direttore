import pytest
from api.services.containerlab._base import (
    oldest_created_at,
    build_labs_from_containers,
    normalize_inspect,
)


def test_oldest_created_at_returns_none_for_empty():
    assert oldest_created_at([]) is None


def test_oldest_created_at_returns_earliest():
    containers = [
        {"createdAt": "2024-01-02T00:00:00Z"},
        {"createdAt": "2024-01-01T00:00:00Z"},
    ]
    assert oldest_created_at(containers) == "2024-01-01T00:00:00Z"


def test_oldest_created_at_handles_alternate_keys():
    containers = [{"Created": "2024-03-01T00:00:00Z"}]
    assert oldest_created_at(containers) == "2024-03-01T00:00:00Z"


def test_build_labs_groups_by_lab_name():
    containers = [
        {"lab_name": "mylab", "lab_path": "/t/mylab.yml", "createdAt": "2024-01-01T00:00:00Z"},
        {"lab_name": "mylab", "lab_path": "/t/mylab.yml", "createdAt": "2024-01-02T00:00:00Z"},
        {"lab_name": "other", "lab_path": "/t/other.yml", "createdAt": "2024-01-03T00:00:00Z"},
    ]
    labs = build_labs_from_containers(containers)
    assert len(labs) == 2
    mylab = next(l for l in labs if l["name"] == "mylab")
    assert len(mylab["containers"]) == 2
    assert mylab["created_at"] == "2024-01-01T00:00:00Z"


def test_normalize_inspect_list():
    data = [{"name": "c1"}]
    assert normalize_inspect(data) == {"containers": [{"name": "c1"}]}


def test_normalize_inspect_dict_with_containers_key():
    data = {"containers": [{"name": "c1"}]}
    assert normalize_inspect(data) == {"containers": [{"name": "c1"}]}


def test_normalize_inspect_clab_074_format():
    # ContainerLab 0.74+ returns {"lab-name": [container, ...]}
    data = {"mylab": [{"name": "c1"}, {"name": "c2"}]}
    result = normalize_inspect(data)
    assert len(result["containers"]) == 2


def test_normalize_inspect_empty_dict():
    assert normalize_inspect({}) == {"containers": []}
