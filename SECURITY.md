# Security

Report vulnerabilities privately through GitHub Security Advisories for this
repository.

Pull request contents are untrusted input. The action intentionally uses the
`pull_request` event and an example same-repository guard so forked code cannot
access model credentials. Do not replace this with `pull_request_target`
without a separate threat model and isolated credentials.

The reviewer has terminal and file tools inside the checked-out repository.
Run it on GitHub-hosted or otherwise isolated runners, keep it advisory, and do
not expose secrets beyond the model key and least-privilege review token.
