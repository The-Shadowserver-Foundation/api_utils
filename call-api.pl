#!/usr/bin/env perl

=head1 NAME

call-api.pl : Shadowserver Foundation API Utility

=head1 DESCRIPTION

This script requires your API details to be stored in ~/.shadowserver.api 
with the following contents:

--
[api]
key = 123456798
secret = MySecret
uri = https://transform.shadowserver.org/api2/
--

This script may be called with two or three arguments:

    call-api.pl <method> <request> [pretty|binary]

The request must be a valid JSON object.

Simple usage:

$ ./call-api.pl test/ping '{}' 
{"pong":"2020-10-26 23:06:37"}

Pretty output:

$ ./call-api.pl test/ping '{}' pretty
{
    "pong": "2020-10-26 23:06:42"
}

=cut

use Config::Simple;
use JSON;
use Digest::SHA qw(hmac_sha256_hex);
use LWP::UserAgent;
use HTTP::Request;
use URI;
use strict;

my $config = eval { new Config::Simple($ENV{'HOME'} . "/.shadowserver.api") };

my $TIMEOUT = 45;


=item api_call( $method, \%request )

Call the specified api method with a request dictionary.

=cut
sub api_call
{
	my ($method, $request) = @_;

	my $url = $config->param("api.uri") . $method;

	$request->{'apikey'} = $config->param('api.key');
    my $request_string = encode_json($request);
	my $hmac2 = hmac_sha256_hex($request_string, $config->param('api.secret'));

	my $ua = new LWP::UserAgent();
	$ua->timeout($TIMEOUT);

	my $ua_request = new HTTP::Request('POST', $url, [ 'HMAC2' => $hmac2 ] );
	$ua_request->content($request_string);
	my $response = $ua->request($ua_request);
	return $response->content;
}

unless (caller) # main
{

    if (scalar @ARGV < 2)
	{
        print STDERR "Usage: call-api.pl method json [pretty|binary]\n";
		exit(1);
	}

	my $api_request = eval { decode_json($ARGV[1]) };
	if ($@)
	{
		print STDERR "JSON Exception: $@\n";
		exit(1);
	}

	if (!defined($config) || $config->param('api.key') eq '')
	{
		print STDERR "Exception: api.key not defined in " . $ENV{'HOME'} 
			. "/.shadowserver.api\n";
		exit(1);
	}

    my $res = eval { api_call($ARGV[0], $api_request) };
	if ($@)
	{
		print STDERR "API Exception: $@\n";
		exit(1);
	}

    if (scalar @ARGV > 2)
	{
		if ($ARGV[2] eq "pretty")
		{
			eval { print to_json(decode_json($res), { pretty => 1}), "\n" };
			exit(0) unless ($@);
		}
    	elsif ($ARGV[2] eq "binary")
		{
			binmode(STDOUT);
			write(STDOUT, $res);
			exit(0);
		}
		else
		{
			die('Unknown option ' . $ARGV[2]);
		}
	}

	print $res, "\n";
}
