# iFixit repairability dashboard

The `gh-pages` branch contains the static dashboard. Python collection code and
its daily data workflow live on `master`.

## Build local assets

Use Node.js 24, then run:

```sh
npm ci
npm run build
```

Tailwind CSS is compiled from `css/input.css` and `css/site.css` into `styles.css`.
The build scans the HTML and application scripts, including dynamically generated
classes. Edit the source CSS, then rebuild; do not edit the generated stylesheet.

Chart.js and JetBrains Mono are copied from exact, locked npm package versions
into `assets/`, together with their licenses. The dashboard requests no remote
stylesheets, fonts, or scripts. Font subsets load only when their characters are
needed. Assets are committed so GitHub Pages can serve them without a Node build.
Update a dependency with npm, run the build, and commit the lockfile plus generated
assets. Downloads happen during installation, not on each page visit.

The browser workflow rebuilds and checks that generated files match their sources.
See [tests/README.md](tests/README.md) for browser checks and supported viewports.
