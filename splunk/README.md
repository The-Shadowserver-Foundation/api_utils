
# Shadowserver Reports for Splunk

This is a Splunk Modular Input Add-On for indexing Shadowserver intelligence reports.

## Sample Configuration

This section provides an example configuration of the Add-On using Slack Enterprise 9.1.1.

From the _Settings_ menu, select **Data**|Data inputs.

In the list of _Local inputs_ locate _Shadowserver Reports_ and click the **+ Add new** link to the right.

![image](https://github.com/The-Shadowserver-Foundation/api_utils/assets/16844541/b752ffcf-5c27-4001-b99c-297af16be4fa)

The _name_, _API Key_, and _API secret_ fields are required.  

Check the _More settings_ box to set the desired interval to check for reports.  If the _interval_ field is not set, the add-on will only run once.

The interval can be set to `3600` for hourly or `15 * * * *` to check 15 minutes after every hour.

A cron schedule has five elements (from left to right):

    Minute: 0-59
    Hour: 0-23
    Day of the month: 1-31
    Month: 1-12
    Day of the week: 0-6 (where 0 = Sunday)

The destination index may also be set after checking the _More settings_ box.

Multiple instances of the Add-on can be created to partition events into different destinations by specifying _Reports_ and/or _Types_.
