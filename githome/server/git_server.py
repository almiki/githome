import os
import re
import subprocess
import time
import threading
import urlparse

from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler


_refs_re = re.compile("^/([^/]+)/info/refs$")
_post_re = re.compile("^/([^/]+)/(git-[a-z]+-pack)$")

_service_re = re.compile("^git-[a-z\\-]+$")


def _create_handler(repo_dir, bin_dir, lib_dir):
    # bin_dir is the location of the git binaries we'll execute.
    # lib_dir is the location of required dlls on Windows, which we'll use as
    # the cwd so they get loaded.

    if lib_dir is None:
        lib_dir = bin_dir

    repo_names = []
    repo_dir_contents = os.listdir(repo_dir)
    for thing in repo_dir_contents:
        path = os.path.join(repo_dir, thing)
        if os.path.isdir(path):
            repo_names.append(thing)

    print "Found repos {}".format(repo_names)
    repo_names = set(repo_names)


    class h(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse.urlparse(self.path)
            params = urlparse.parse_qs(parsed.query)

            service = params['service'][0]
            if _service_re.match(service) is None:
                self.send_error(404)
                return

            url_match = _refs_re.match(parsed.path)
            if url_match is None:
                self.send_error(404)
                return

            project = url_match.group(1)
            if project not in repo_names:
                self.send_error(404)
                return

            project = os.path.join(repo_dir, project)

            cmd = [os.path.join(bin_dir, service) if bin_dir is not None else service,
                   '--stateless-rpc', '--advertise-refs',
                   os.path.join(repo_dir, project)]

            p = subprocess.Popen(cmd, cwd=lib_dir, stdout=subprocess.PIPE)

            stdout, _ = p.communicate()

            if p.returncode != 0:
                self.send_error(500)
                return

            data = '# service={}\n'.format(service)
            data = "{:04x}".format(len(data) + 4) + data + '0000' + stdout

            self.send_response(200)
            self.send_header("Content-Type", 'application/x-{}-advertisement'.format(service))
            self.send_header("Connection", "close")
            self.end_headers()

            self.wfile.write(data)

        def do_POST(self):
            parsed = urlparse.urlparse(self.path)
            match = _post_re.match(parsed.path)
            if match is None:
                self.send_error(404)
                return

            project = match.group(1)
            if project not in repo_names:
                self.send_error(404)
                return

            action = match.group(2)

            if action in ("git-upload-pack", "git-receive-pack",):
                cmd = [os.path.join(bin_dir, action) if bin_dir is not None else action,
                       '--stateless-rpc',
                       os.path.join(repo_dir, project)]
                p = subprocess.Popen(cmd, cwd=lib_dir, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

                process_input = self.rfile.read(int(self.headers['content-length']))

                data, _ = p.communicate(process_input)
                if p.returncode != 0:
                    self.send_response(500)
                    return

                self.send_response(200)
                self.send_header("Content-Type", 'application/x-{}-result'.format(action))
                self.send_header("Connection", "close")
                self.end_headers()

                self.wfile.write(data)
            else:
                self.send_error(404)
                return

    return h


class GitServer(object):
    def __init__(self, **kwargs):
        self._port = int(kwargs['port'])
        self._dir = kwargs['dir']
        self._bin_dir = kwargs['bin_dir']
        self._lib_dir = kwargs['lib_dir']

        self._server = None
        self._run_thread = None

    def start(self):
        self._run_thread = threading.Thread(target=self._run)
        self._run_thread.daemon = True
        self._run_thread.start()

    def _run(self):
        self._server = HTTPServer(('', self._port), _create_handler(self._dir, self._bin_dir, self._lib_dir))
        self._server.serve_forever()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._run_thread.join()

            self._server = self._run_thread = None


if __name__ == "__main__":
    import argparse

    # Note: there's no security whatsoever in this thing, so don't use it for
    # anything other than personal home network stuff.

    # Windows examples:
    # bin_dir: r"C:\Program Files\Git\mingw64\libexec\git-core"
    # lib_dir: r"C:\Program Files\Git\mingw64\bin"

    p = argparse.ArgumentParser(description='Super simple git server.')
    p.add_argument('--port', '-p', default=7811, dest="port", help="The port to listen on")
    p.add_argument('--repo_dir', '-r', default='.', dest="repo_dir", help="The directory containing git repos")
    p.add_argument('--bin_dir', '-b', required=False, dest="bin_dir", help="The location of the git binaries (e.g. git-upload-pack)")
    p.add_argument('--lib_dir', '-l', required=False, dest="lib_dir", help="The location of required git libraries (dlls on Windows, used as cwd)")
    args = p.parse_args()

    print "Starting server on port {}".format(args.port)
    print "Using repo dir {}".format(args.repo_dir)

    if args.bin_dir is not None:
        print "Using git bin dir {}".format(args.bin_dir)

    if args.lib_dir is not None:
        print "Using git lib dir {}".format(args.lib_dir)

    server = GitServer(port=args.port,
                       dir=args.repo_dir,
                       bin_dir=args.bin_dir,
                       lib_dir=args.lib_dir)
    server.start()

    # Just run forever
    while True:
        time.sleep(1)
