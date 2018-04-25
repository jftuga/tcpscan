# tcpscan
A fast, simple, multi-threaded IPv4 TCP port scanner

This will run under Windows, Linux and MaxOS. 

A windows executable is located on the [releases page](https://github.com/jftuga/tcpscan/releases).

```

tcpscan --help


    usage: tcpscan.py [-h] [-x SKIPNETBLOCK] [-X SKIPPORTS] [-p PORTS]
                      [-T THREADS] [-t TIMEOUT] [-s] [-S] [-c] [-o OUTPUT] [-d]
                      [-v] [-r RUNTIME] [-l LOOP] [-lo] [-lc] [-L]
                      [target]
    
    tcpscan: a simple, multi-threaded IPv4 TCP port scanner
    
    positional arguments:
      target                e.g. 192.168.1.0/24 192.168.1.100 www.example.com
    
    optional arguments:
      -h, --help            show this help message and exit
      -x SKIPNETBLOCK, --skipnetblock SKIPNETBLOCK
                            skip a sub-netblock, e.g. 192.168.1.96/28
      -X SKIPPORTS, --skipports SKIPPORTS
                            exclude a subset of ports, e.g. 135-139
      -p PORTS, --ports PORTS
                            comma separated list or hyphenated range, e.g.
                            22,80,443,445,515 e.g. 80-515 e.g. all
      -T THREADS, --threads THREADS
                            number of concurrent threads, default: 100
      -t TIMEOUT, --timeout TIMEOUT
                            number of seconds to wait for a connect, default: 0.07
                            for lan, 0.18 for wan
      -s, --shufflehosts    randomize the order IPs are scanned
      -S, --shuffleports    randomize the order ports are scanned
      -c, --closed          output ports that are closed
      -o OUTPUT, --output OUTPUT
                            output to CSV file
      -d, --dns             revolve IPs to dns names
      -v, --verbose         output statistics
      -r RUNTIME, --runtime RUNTIME
                            periodically display runtime stats every RUNTIME
                            seconds to STDERR
      -l LOOP, --loop LOOP  repeat the port scan LOOP times, 0 for continuous
      -lo, --loopopen       repeat the port scan until all port(s) are open
      -lc, --loopclose      repeat the port scan until all port(s) are closed
      -L, --listen          listen on given TCP port(s) for incoming connection(s)
                            [mutually exclusive; but works with --output and
                            --dns]
    
    tcpscan version: 1.32
```
