from laclaugpt_data_collection.profiles import laptop, linux_server


def test_laptop_and_server_profiles_are_composable() -> None:
    local = laptop("data")
    assert local.machine == "laptop"
    assert local.browser == "firefox-local"

    server = linux_server(storage="distributed")
    assert server.machine == "linux-server"
    assert server.execution == "cron"
    assert server.browser == "none"
    assert server.storage == "distributed"
