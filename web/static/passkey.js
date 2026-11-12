// Passkey (WebAuthn) helpers for the Bastion web admin.
// Served as a static file so it is covered by the page's Content-Security-Policy.
(function () {
    'use strict';

    function b64urlToBytes(value) {
        var pad = '='.repeat((4 - (value.length % 4)) % 4);
        var raw = atob((value + pad).replace(/-/g, '+').replace(/_/g, '/'));
        var out = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) { out[i] = raw.charCodeAt(i); }
        return out.buffer;
    }

    function bytesToB64url(buffer) {
        var bytes = new Uint8Array(buffer);
        var raw = '';
        for (var i = 0; i < bytes.length; i++) { raw += String.fromCharCode(bytes[i]); }
        return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    }

    function csrfToken() {
        var el = document.querySelector('input[name="csrf_token"]');
        return el ? el.value : '';
    }

    function post(url, body) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
            body: JSON.stringify(body || {})
        }).then(function (resp) {
            return resp.json().catch(function () { return {}; }).then(function (data) {
                if (!resp.ok) { throw new Error(data.error || 'Request failed (' + resp.status + ').'); }
                return data;
            });
        });
    }

    function showError(target, err) {
        var box = document.getElementById(target);
        var text = (err && err.name === 'NotAllowedError')
            ? 'The passkey prompt was cancelled or timed out.'
            : ((err && err.message) || 'Something went wrong.');
        if (box) { box.textContent = text; box.classList.remove('d-none'); } else { alert(text); }
    }

    function supported(target) {
        if (window.PublicKeyCredential && navigator.credentials) { return true; }
        showError(target, new Error('This browser does not support passkeys on this address. Use HTTPS, or the SSH tunnel on http://localhost:8000.'));
        return false;
    }

    function register(label, target) {
        if (!supported(target)) { return; }
        post('/account/passkeys/register/options').then(function (options) {
            options.challenge = b64urlToBytes(options.challenge);
            options.user.id = b64urlToBytes(options.user.id);
            (options.excludeCredentials || []).forEach(function (c) { c.id = b64urlToBytes(c.id); });
            return navigator.credentials.create({ publicKey: options });
        }).then(function (cred) {
            return post('/account/passkeys/register/verify', {
                label: label,
                credential: {
                    id: cred.id,
                    rawId: bytesToB64url(cred.rawId),
                    type: cred.type,
                    response: {
                        clientDataJSON: bytesToB64url(cred.response.clientDataJSON),
                        attestationObject: bytesToB64url(cred.response.attestationObject)
                    }
                }
            });
        }).then(function () {
            window.location.reload();
        }).catch(function (err) { showError(target, err); });
    }

    function login(target) {
        if (!supported(target)) { return; }
        post('/login/passkey/options').then(function (options) {
            options.challenge = b64urlToBytes(options.challenge);
            (options.allowCredentials || []).forEach(function (c) { c.id = b64urlToBytes(c.id); });
            return navigator.credentials.get({ publicKey: options });
        }).then(function (cred) {
            return post('/login/passkey/verify', {
                credential: {
                    id: cred.id,
                    rawId: bytesToB64url(cred.rawId),
                    type: cred.type,
                    response: {
                        clientDataJSON: bytesToB64url(cred.response.clientDataJSON),
                        authenticatorData: bytesToB64url(cred.response.authenticatorData),
                        signature: bytesToB64url(cred.response.signature),
                        userHandle: cred.response.userHandle ? bytesToB64url(cred.response.userHandle) : null
                    }
                }
            });
        }).then(function (data) {
            window.location.href = data.redirect || '/';
        }).catch(function (err) { showError(target, err); });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var loginBtn = document.getElementById('passkeyLogin');
        if (loginBtn) {
            loginBtn.addEventListener('click', function () { login('passkeyError'); });
        }
        var registerForm = document.getElementById('passkeyRegister');
        if (registerForm) {
            registerForm.addEventListener('submit', function (event) {
                event.preventDefault();
                register(document.getElementById('passkeyLabel').value, 'passkeyError');
            });
        }
    });
})();
