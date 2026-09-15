from laclaugpt_data_collection.profiles import laptop, linux_server
def test_laptop_and_server_profiles_are_composable():
 p=laptop('data'); p.validate(); assert p.browser=='firefox-local'
 s=linux_server(storage='distributed'); s.validate(); assert s.execution=='cron' and s.browser=='none'
