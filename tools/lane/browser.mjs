// Drive a lane's frontend in real Google Chrome, with a visible window by default, through playwright-core.
// Import openLane() for your own flows, or use shot.mjs for a one-off screenshot.
//
//   import { openLane } from '<skill>/scripts/browser.mjs';
//   const { page, close } = await openLane({ as: 'e2e-professor@example.com' });
//   await page.goto('/professor/courses'); await page.screenshot({ path: 'proof/01-courses.png' });
//   await close();
//
// Env (set by `lane shot`, or export yourself): LANE_FE=http://localhost:<fe port>, LANE_DIR=<lane folder>,
// LANE_SCRIPTS=<this folder>, LANE_N=<lane number>. HEADLESS=1 hides the window. Use it only when there is no other option,
// and say why in the Method line of the repro file.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { basename, join } from 'node:path';
import { chromium } from 'playwright-core';

const PASSWORDS = { 'test@example.com': 'password123' };

function env(name) {
	const v = process.env[name];
	if (!v) throw new Error(`${name} is not set; run through 'lane shot' or export it (lane info <N>)`);
	return v;
}

function totp(email) {
	return execFileSync('python3', [join(env('LANE_SCRIPTS'), 'lane-login.py'), '--totp', email], {
		env: { ...process.env, TOTP_STORE: join(env('LANE_DIR'), '.totp-secrets.json') },
	})
		.toString()
		.trim();
}

function enrolTotp(email, password) {
	// Logging in once over the API enrols TOTP for admins and stores the secret for this lane.
	const api = `http://127.0.0.1:${Number(new URL(env('LANE_FE')).port) + 80}`;
	execFileSync('python3', [join(env('LANE_SCRIPTS'), 'lane-login.py'), email, password], {
		env: { ...process.env, QA_BE: api, TOTP_STORE: join(env('LANE_DIR'), '.totp-secrets.json') },
		stdio: ['ignore', 'ignore', 'inherit'],
	});
}

async function uiLogin(page, email, password) {
	await page.goto('/login', { waitUntil: 'domcontentloaded' });
	await page.locator('#email').fill(email);
	await page.locator('#password').fill(password);
	await page.getByRole('button', { name: 'LOG IN' }).click();
	const verify = page.getByTestId('two-factor-verify');
	const setup = page.getByTestId('two-factor-setup');
	const landed = page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 30_000 });
	const which = await Promise.race([
		landed.then(() => 'in'),
		verify.waitFor({ timeout: 30_000 }).then(() => 'verify'),
		setup.waitFor({ timeout: 30_000 }).then(() => 'setup'),
	]);
	if (which === 'setup') throw new Error(`${email} needs TOTP setup; this should not happen after enrolTotp`);
	if (which === 'verify') {
		// A code is accepted once per 30 s step. If the API enrolment just used this step's code, wait.
		for (let attempt = 0; attempt < 3; attempt++) {
			await page.getByLabel('Authentication code').fill(totp(email));
			await page.getByRole('button', { name: 'Verify' }).click();
			try {
				await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 10_000 });
				return;
			} catch {
				await page.waitForTimeout((31 - (Date.now() / 1000) % 30) * 1000);
			}
		}
		throw new Error(`TOTP verify failed for ${email}`);
	}
}

export async function openLane({ as = 'e2e-professor@example.com', password, viewport = { width: 1440, height: 900 } } = {}) {
	const base = env('LANE_FE');
	const pw = password ?? PASSWORDS[as] ?? 'Test123!';
	const authDir = join(env('LANE_DIR'), '.auth');
	mkdirSync(authDir, { recursive: true });
	const statePath = join(authDir, `${as}.json`);
	const browser = await chromium.launch({ channel: 'chrome', headless: !!process.env.HEADLESS });
	const ctxOpts = { baseURL: base, viewport };
	let context = await browser.newContext(existsSync(statePath) ? { ...ctxOpts, storageState: statePath } : ctxOpts);
	context.setDefaultTimeout(60_000); // Playwright's default is no limit: a stuck click would hang the run
	let page = await context.newPage();
	// /settings needs a session for every role, so landing on /login means we are not signed in.
	await page.goto('/settings', { waitUntil: 'domcontentloaded' });
	await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
	if (new URL(page.url()).pathname.startsWith('/login')) {
		if (/admin|isa/.test(as)) enrolTotp(as, pw);
		await context.close();
		context = await browser.newContext(ctxOpts);
		context.setDefaultTimeout(60_000);
		page = await context.newPage();
		await uiLogin(page, as, pw);
		await context.storageState({ path: statePath });
	}
	const relogin = async () => {
		await uiLogin(page, as, pw);
		await context.storageState({ path: statePath });
	};
	// goto() that signs in again if the session was bounced to /login, then returns to the target.
	const goto = async (path, opts = { waitUntil: 'domcontentloaded' }) => {
		await page.goto(path, opts);
		if (new URL(page.url()).pathname.startsWith('/login')) {
			await relogin();
			await page.goto(path, opts);
		}
		await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {});
	};
	return { browser, context, page, goto, close: () => browser.close() };
}

// Numbered screenshots for a flow. Every shot needs a purpose: one line on what it shows and why it is
// here. It goes into the flow's log as `SHOT NN-<name>.png: <purpose>`, ready for the repro file's
// "looking at" column. A shot byte for byte the same as the one before shows nothing new, so it is not
// saved; the log says `SAME NN-<name>.png not saved` and names the earlier file. Pass { always: true }
// for a shot that must be kept anyway, such as the screen when a step failed.
//
//   const shot = proofShots(page, PROOF, log);
//   const { file, saved } = await shot(3, 'save-button-after-empty-course', 'Save button after saving a course with no chapters');
export function proofShots(page, dir, log) {
	let last = null;
	return async function shot(no, name, purpose, { always = false } = {}) {
		if (!String(purpose ?? '').trim()) throw new Error(`screenshot ${name} has no purpose; say what it shows and why it is here`);
		const file = join(dir, `${String(no).padStart(2, '0')}-${name}.png`);
		const bytes = await page.screenshot({ fullPage: true });
		if (!always && last && bytes.equals(last.bytes)) {
			log(`  SAME ${basename(file)} not saved: the screen is identical to ${basename(last.file)} (${purpose})`);
			return { file: last.file, saved: false };
		}
		writeFileSync(file, bytes);
		last = { file, bytes };
		log(`  SHOT ${basename(file)}: ${purpose}`);
		return { file, saved: true };
	};
}
