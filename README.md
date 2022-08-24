# api_utils
Sample programs to access the API

Here are two programs, one in Python and one in Perl to help with the execution and accessing the data through the API’s.

For either of these programs to function, they expect a file called ~/.shadowserver.api to exist and to contain your API key and secret. As an example:

```
[api]
key = <<API-KEY>>
secret = <<SECRET>>
uri = https://transform.shadowserver.org/api2/
```

If an error like this occurs, it means that the query is going through a lot of data and the timeout in the program should be increased:

```
freed0@pit:~$ ./call-api.py reports/query '{"report":"united-states", "date":"2020-10-27", "query":{"city":"ashburn"}, "limit":3}' pretty
API Exception: The read operation timed out
```

Additional details can be found at https://www.shadowserver.org/what-we-do/network-reporting/api-documentation/.

