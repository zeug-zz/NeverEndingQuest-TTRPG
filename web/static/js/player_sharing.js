// TABLETOP MODE: Facilitator-local player sharing controls for the host UI only.
(function () {
    'use strict';

    const panel = document.getElementById('player-sharing-panel');
    if (!panel) return;

    const statusLine = document.getElementById('player-sharing-status');
    const secretModal = document.getElementById('player-sharing-secret');
    const secretValue = document.getElementById('player-sharing-secret-value');
    const buttons = {
        initialize: document.getElementById('player-sharing-initialize'),
        issue: document.getElementById('player-sharing-issue'),
        start: document.getElementById('player-sharing-start'),
        copy: document.getElementById('player-sharing-copy'),
        rotate: document.getElementById('player-sharing-rotate'),
        revoke: document.getElementById('player-sharing-revoke'),
        stop: document.getElementById('player-sharing-stop'),
        refresh: document.getElementById('player-sharing-refresh')
    };

    function safeCode(value) {
        return typeof value === 'string' && /^[a-z][a-z0-9_]{0,47}$/.test(value)
            ? value
            : 'operation_failed';
    }

    function setStatus(state, reason) {
        statusLine.textContent = 'Sharing: ' + safeCode(state) + ' (' + safeCode(reason) + ')';
    }

    function renderStatus(status) {
        if (!status || typeof status !== 'object') {
            setStatus('failed', 'operation_failed');
            return;
        }
        const state = safeCode(status.state);
        const reason = safeCode(status.reason);
        setStatus(state, reason);
        const initialized = status.identity_initialized === true;
        buttons.initialize.disabled = initialized;
        buttons.issue.disabled = !initialized;
        buttons.start.disabled = !initialized;
        buttons.copy.disabled = state !== 'ready';
        buttons.rotate.disabled = !initialized;
        buttons.revoke.disabled = status.credential_state !== 'present';
        buttons.stop.disabled = state === 'off' || state === 'initializing_required';
    }

    async function parseResponse(response) {
        let payload = null;
        try {
            payload = await response.json();
        } catch (_error) {
            payload = null;
        }
        if (!response.ok || !payload || payload.ok !== true) {
            const reason = payload ? safeCode(payload.reason) : 'service_unavailable';
            throw new Error(reason);
        }
        return payload;
    }

    async function refreshStatus() {
        try {
            const response = await fetch('/api/player-sharing/status', {
                method: 'GET',
                cache: 'no-store',
                credentials: 'same-origin',
                headers: { 'Accept': 'application/json' }
            });
            const payload = await parseResponse(response);
            renderStatus(payload.status);
        } catch (error) {
            setStatus('failed', safeCode(error.message));
        }
    }

    async function postAction(path) {
        const response = await fetch('/api/player-sharing/' + path, {
            method: 'POST',
            cache: 'no-store',
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({})
        });
        return parseResponse(response);
    }

    function clearSecret() {
        secretValue.textContent = '';
        secretModal.hidden = true;
    }

    function showSecret(credential) {
        clearSecret();
        secretValue.textContent = credential;
        secretModal.hidden = false;
        document.getElementById('player-sharing-dismiss').focus();
    }

    async function runAction(path, secretField) {
        try {
            let payload = await postAction(path);
            if (payload.status) renderStatus(payload.status);
            if (secretField === 'credential') {
                let credential = payload.credential;
                if (typeof credential !== 'string' || !credential) {
                    setStatus('failed', 'credential_unavailable');
                } else {
                    showSecret(credential);
                }
                credential = '';
                payload.credential = '';
            }
            payload = null;
        } catch (error) {
            setStatus('failed', safeCode(error.message));
            await refreshStatus();
        }
    }

    buttons.initialize.addEventListener('click', function () {
        const confirmed = window.confirm(
            'Initialize the OpenTunnel identity once for this local profile? This is an explicit host-only action.'
        );
        if (!confirmed) return;
        fetch('/api/player-sharing/initialize-identity', {
            method: 'POST',
            cache: 'no-store',
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ confirm: true })
        }).then(parseResponse).then(function (payload) {
            renderStatus(payload.status);
        }).catch(function (error) {
            setStatus('failed', safeCode(error.message));
            refreshStatus();
        });
    });

    buttons.issue.addEventListener('click', function () {
        runAction('issue-access', 'credential');
    });

    buttons.start.addEventListener('click', function () {
        runAction('start');
    });

    buttons.copy.addEventListener('click', async function () {
        let invitation = '';
        let payload = null;
        try {
            payload = await postAction('copy-invitation');
            invitation = payload.invitation;
            if (typeof invitation !== 'string' || !invitation) {
                throw new Error('invitation_unavailable');
            }
            await navigator.clipboard.writeText(invitation);
            if (payload.status) renderStatus(payload.status);
            setStatus('ready', 'invitation_copied');
        } catch (error) {
            setStatus('failed', safeCode(error.message) === 'operation_failed'
                ? 'clipboard_unavailable'
                : safeCode(error.message));
        } finally {
            invitation = '';
            if (payload) payload.invitation = '';
            payload = null;
        }
    });

    buttons.rotate.addEventListener('click', function () {
        if (!window.confirm('Rotate player access? Existing player sessions will be invalidated.')) return;
        runAction('rotate', 'credential');
    });

    buttons.revoke.addEventListener('click', function () {
        if (!window.confirm('Revoke player access and disconnect active player sessions?')) return;
        runAction('revoke');
    });

    buttons.stop.addEventListener('click', function () {
        if (!window.confirm('Stop sharing and disconnect player sessions?')) return;
        runAction('stop');
    });

    buttons.refresh.addEventListener('click', refreshStatus);
    document.getElementById('player-sharing-dismiss').addEventListener('click', clearSecret);
    window.addEventListener('pagehide', clearSecret);
    refreshStatus();
}());
