/**
 * Screenshot harness for the Crew Members roster's "+" entry (issue #9513):
 * pressing it must land ON the crew manager's create form, not on the crew
 * list a second "New crew" click would be needed on. Against a REAL pod.
 *
 * Frames, per theme:
 *   01-members-roster    the roster with the "+" at rest (before)
 *   02-create-form       one click later: the "Create a new agent" form is
 *                        open, the URL has consumed `new=1&from=members`
 *
 * Usage:
 *   kirocrew pod up <worktree> --json | tail -1 > "$KIROCREW_SCRATCH/pod-info.json"
 *   POD_INFO="$KIROCREW_SCRATCH/pod-info.json" \
 *     node scripts/capture-members-add-opens-create.mjs ../temp-screenshots/members-add-opens-create
 */
import { chromium } from 'playwright'
import { mkdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { check, podInfo, primeCrewPod } from './lib/crew-pod-harness.mjs'

const OUT = process.argv[2] || '../temp-screenshots/members-add-opens-create'
const CREW = 'oncall'
const ADD_MEMBER = 'Add member'
const CREATE_TITLE = 'Add crew member' // the create-mode DialogContent's aria-label when arriving from the roster

mkdirSync(OUT, { recursive: true })
const { BASE, authed } = podInfo(readFileSync)

async function shoot(browser, theme) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } })
  await primeCrewPod(page, authed, CREW, theme)

  await page.goto(`${BASE}/members`, { waitUntil: 'domcontentloaded' })
  const add = page.getByTestId('member-add')
  await add.waitFor({ state: 'visible', timeout: 20000 })
  check(`[${theme}] roster "+" is named "${ADD_MEMBER}"`, (await add.getAttribute('aria-label')) === ADD_MEMBER)
  await page.getByTestId('member-roster').getByText(CREW).first().waitFor({ state: 'visible', timeout: 20000 })
  await page.waitForTimeout(400)
  await page.screenshot({ path: join(OUT, `01-members-roster-${theme}.png`) })

  await add.click()
  const form = page.getByRole('dialog', { name: CREATE_TITLE })
  await form.waitFor({ state: 'visible', timeout: 20000 })
  check(`[${theme}] one click lands on the "${CREATE_TITLE}" form`, true)
  check(`[${theme}] the form is titled in the roster's words, not "Create Agent"`,
    (await form.getByRole('heading', { name: CREATE_TITLE }).count()) === 1)
  await page.waitForFunction(() => !/[?&](new|from)=/.test(location.search), null, { timeout: 10000 })
  check(`[${theme}] deep-link params consumed`, /[?&]tab=crews/.test(page.url()) && !/[?&](new|from)=/.test(page.url()), page.url())
  await page.waitForTimeout(400)
  await page.screenshot({ path: join(OUT, `02-create-form-${theme}.png`) })

  // Fill the form and create: the landing is the NEW member's thread on the
  // Members page, not the crew list behind the form.
  const newName = `scribe-${theme}`
  await form.getByPlaceholder('e.g. oncall').fill(newName)
  const template = form.getByRole('combobox', { name: 'Agent Template' })
  await template.click()
  await page.getByRole('option', { name: 'kirocrew', exact: true }).click()
  await form.getByRole('button', { name: 'Create', exact: true }).click()
  await page.waitForURL((u) => u.pathname === '/members' && u.searchParams.get('member') === newName, { timeout: 20000 })
  check(`[${theme}] create lands on /members?member=${newName}`, true)
  const header = page.getByTestId('member-thread-header')
  await header.getByText(newName).first().waitFor({ state: 'visible', timeout: 20000 })
  check(`[${theme}] the new member's thread is open`, true)
  check(`[${theme}] no "gone" notice on arrival`, (await page.getByTestId('member-gone-notice').count()) === 0)
  await page.waitForTimeout(500)
  await page.screenshot({ path: join(OUT, `03-after-create-landing-${theme}.png`) })
  await page.close()
}

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined })
try {
  for (const theme of ['light', 'dark']) await shoot(browser, theme)
} finally {
  await browser.close()
}
console.log('wrote', OUT)
