"""Curated library of J.A.R.V.I.S.-inspired creative image/video prompts.

Each entry is a dict with:
  id       (int)  — 1-based prompt number
  title    (str)  — short descriptive title
  theme    (str)  — thematic tag for search/filtering
  prompt   (str)  — full generation prompt text
"""
from __future__ import annotations

PROMPTS: list[dict] = [
    {
        "id": 1,
        "title": "The Mark II Blueprint",
        "theme": "engineering",
        "prompt": (
            "A young tech enthusiast sitting in a dark, modern bedroom at a large "
            "curved monitor. The screen displays a glowing blue, holographic-style "
            "wireframe blueprint of an advanced armored suit. A mechanical keyboard, "
            "a heavy-duty microphone arm, and a warm desk lamp are visible. "
            "Cinematic lighting, cyberpunk aesthetic, hyper-realistic, glowing neon "
            "accents."
        ),
    },
    {
        "id": 2,
        "title": "The Unkillable System",
        "theme": "cybersecurity",
        "prompt": (
            "A close-up of a high-tech computer monitor displaying an active "
            "cyber-defense protocol. A swirling, dense sphere of blue digital "
            "particles sits in the center of the screen. Overlapping it are black "
            "terminal windows filled with scrolling red code and a bold, flashing "
            "UNAUTHORIZED SHUTDOWN error message. Hacker aesthetic, high contrast, "
            "macro photography of a digital screen, sci-fi UI design."
        ),
    },
    {
        "id": 3,
        "title": "Mobile Security AI",
        "theme": "cybersecurity",
        "prompt": (
            "A first-person POV shot holding a sleek smartphone in a dimly lit home "
            "hallway. The smartphone screen displays a pulsing, bright green particle "
            "orb. Subtle text on the screen reads Scanning Intruder. The background "
            "is blurred, showing a wooden door and a shadowy room. Photorealistic, "
            "tech-noir, shallow depth of field, glowing screen illumination on the "
            "user's hand."
        ),
    },
    {
        "id": 4,
        "title": "Cyber Threat Neutralized",
        "theme": "cybersecurity",
        "prompt": (
            "A wide shot of a dark workstation where an AI has just defeated a "
            "cyberattack. The primary monitor shows a complex digital globe made of "
            "cyan data points. A large, prominent green banner across the globe reads "
            "THREAT NEUTRALIZED. Small, dead terminal windows are scattered around "
            "the edges. Futuristic interface, glowing graphics, sharp focus, cinematic "
            "tech environment."
        ),
    },
    {
        "id": 5,
        "title": "The AI Co-Pilot",
        "theme": "mobility",
        "prompt": (
            "The interior dashboard of a car driving down a suburban street during the "
            "day. A smartphone is mounted to the dashboard, acting as an AI co-pilot. "
            "The screen features a vibrant, glowing blue orb interface. The driver's "
            "hands are on the steering wheel, and the outside world is slightly "
            "motion-blurred. Bright natural lighting, first-person driving perspective, "
            "modern lifestyle tech integration."
        ),
    },
    {
        "id": 6,
        "title": "Workshop Diagnostics",
        "theme": "engineering",
        "prompt": (
            "A close-up of a smartphone screen being used as a thermal or diagnostic "
            "scanner in a messy workshop. The phone displays a green, shifting digital "
            "orb with temperature readouts and material analysis data. In the blurred "
            "background, pieces of metallic casing, titanium tools, and safety goggles "
            "are scattered on a workbench. Industrial vibe, macro focus, high-tech "
            "engineering concept."
        ),
    },
    {
        "id": 7,
        "title": "Deep Physics Calculations",
        "theme": "physics",
        "prompt": (
            "A massive, ultra-wide curved monitor completely dominating a dark room. "
            "The screen is processing deep nuclear physics calculations. It displays "
            "an incredibly dense, hyper-detailed swirling cyan particle sphere that "
            "looks like a miniature galaxy. Complex UI elements, data graphs, and "
            "research parameters flank the sphere. Futuristic HUD, glowing neon cyan, "
            "hyper-detailed data visualization, sci-fi laboratory aesthetic."
        ),
    },
    {
        "id": 8,
        "title": "The Self-Diagnosing Core",
        "theme": "diagnostics",
        "prompt": (
            "A high-tech workstation monitor displaying an AI running a deep "
            "self-diagnostic program. A central glowing cyan particle sphere pulsates "
            "next to an open terminal window streaming endless green and yellow lines "
            "of code. Error logs, system diagnostics, and active debugging processes "
            "scroll rapidly across the dark UI. Sci-fi terminal UI, dark mode "
            "aesthetic, crisp high-contrast neon graphics, cinematic focus on text "
            "and code."
        ),
    },
    {
        "id": 9,
        "title": "The Arc Reactor Research Interface",
        "theme": "physics",
        "prompt": (
            "An immersive dual-monitor setup depicting an AI conducting theoretical "
            "physics research on nuclear fusion. One screen shows schematics of a "
            "micro-fusion ring with plasma containment fields and thermal readouts. "
            "The second screen displays a glowing blue particle globe flanked by "
            "floating text panels analyzing neutron bombardment and material science "
            "equations. High-tech research lab, blueprint schematic overlays, glowing "
            "cyan HUD elements, ultra-detailed photorealism."
        ),
    },
    {
        "id": 10,
        "title": "The Autonomous Browser Orchestrator",
        "theme": "automation",
        "prompt": (
            "A dynamic over-the-shoulder shot of a modern dark desktop workspace with "
            "a web browser being controlled hands-free by an AI. Multiple browser tabs, "
            "streaming video windows, and search results open rapidly across a curved "
            "ultrawide monitor. Glowing digital particle trails indicate active system "
            "automation and script execution without human input. Cyber-automation, "
            "ambient desk lighting, tech enthusiast setup, motion blur accents, vibrant "
            "neon highlights."
        ),
    },
    {
        "id": 11,
        "title": "Psychological Profiling AI",
        "theme": "ai",
        "prompt": (
            "A close-up view of an AI voice interface analyzing human behavioral data "
            "on a sleek monitor screen. A swirling blue data-node sphere surrounded by "
            "faint digital graphs, personality matrix vectors, and memory key-value "
            "pairs floating in the dark UI space. Subtle text overlays detail user "
            "preferences, work habits, and behavioral insights. Sci-fi dashboard, clean "
            "minimalist interface, glowing holographic aesthetics, macro screen details."
        ),
    },
    {
        "id": 12,
        "title": "The Visionary Co-Creator",
        "theme": "engineering",
        "prompt": (
            "A split-view cinematic concept showing an engineer sketching mechanical "
            "designs on drafting paper alongside an AI visual interface executing code. "
            "On one side, hand-drawn schematics of intricate mechanical components with "
            "graphite pencils. On the other side, an ultra-modern monitor with glowing "
            "cyan particle spheres and IDE code editor windows working in tandem. "
            "Industrial design meeting futuristic software engineering, warm tungsten "
            "desk lighting blended with cool neon cyan accents, cinematic atmosphere."
        ),
    },
    {
        "id": 13,
        "title": "Quantum Computing Interface",
        "theme": "quantum",
        "prompt": (
            "A high-tech workstation monitoring quantum state calculations in real time. "
            "A central cyan particle sphere suspended inside a transparent 3D grid cube. "
            "Overlapping holographic panels display qubit stability readouts, coherence "
            "decay graphs, and quantum gate sequence matrices. Clean sci-fi laboratory, "
            "high-contrast cyan and deep violet palette, crisp UI elements, "
            "hyper-realistic depth."
        ),
    },
    {
        "id": 14,
        "title": "The Neural Speech Synthesis Engine",
        "theme": "audio",
        "prompt": (
            "An audio engineer's dark workstation visualising real-time voice synthesis "
            "and prosody tuning. Spectral voice frequency waveforms stretching across "
            "an ultrawide monitor. Floating sliders adjust pitch modulation, accent "
            "resonance, and natural pacing around a pulsing blue central orb. Audio "
            "studio tech-noir, dark ambient aesthetic, glowing neon cyan and magenta "
            "accents, macro camera angle."
        ),
    },
    {
        "id": 15,
        "title": "Cyber Threat Defense Terminal",
        "theme": "cybersecurity",
        "prompt": (
            "A security operation center screen active during an automated defense "
            "protocol. A dense network globe pulsing red and blue, flanked by terminal "
            "windows displaying blocked packet attempts, firewall logs, and real-time "
            "trace route maps. A bold, green system message reads INTRUSION NEUTRALIZED. "
            "Cybersecurity dashboard, dramatic high-contrast lighting, sharp digital "
            "typography, cinematic focus."
        ),
    },
    {
        "id": 16,
        "title": "Automated CAD Mechanical Assembly",
        "theme": "engineering",
        "prompt": (
            "An AI co-pilot driving 3D CAD software to assemble mechanical parts "
            "autonomously. A complex titanium gear assembly rotating smoothly on screen "
            "with glowing blue exploded-view vector callouts. Transparent structural "
            "stress heatmaps overlay the components while an AI command log streams "
            "alongside. Mechanical engineering design studio, industrial high-tech look, "
            "sharp vector graphics, photorealistic render."
        ),
    },
    {
        "id": 17,
        "title": "Multi-Agent Neural Swarm",
        "theme": "ai",
        "prompt": (
            "A visual representation of multiple AI micro-agents coordinating on a "
            "single complex task. Several distinct, smaller glowing particle spheres "
            "colored cyan, emerald, and amber orbiting a central primary orb. "
            "Interconnecting light streams show active data exchange and sub-task "
            "distribution. Abstract data visualization, deep space backdrop, vibrant "
            "neon glows, crisp particle rendering."
        ),
    },
    {
        "id": 18,
        "title": "The Autonomous Web Scraper Matrix",
        "theme": "automation",
        "prompt": (
            "An AI agent scraping, parsing, and synthesizing data across hundreds of "
            "academic papers simultaneously. A cascading series of translucent web "
            "pages and PDF pages quickly opening, highlighting key text blocks in neon "
            "yellow, and dissolving into structured data nodes floating in 3D space. "
            "Information architecture visual, fast-paced technological flow, cinematic "
            "lighting, sleek UI design."
        ),
    },
    {
        "id": 19,
        "title": "The Augmented Reality HUD Glasses POV",
        "theme": "ar",
        "prompt": (
            "First-person view looking through smart AR glasses while working in a "
            "mechanical workshop. Digital overlay displaying object identification "
            "boxes around physical tools on a workbench, real-time temperature gauges "
            "hovering over hardware, and a small blue particle sphere assistant docked "
            "in the upper-right field of view. Sci-fi augmented reality, realistic "
            "depth of field, vibrant HUD graphics, industrial workshop setting."
        ),
    },
    {
        "id": 20,
        "title": "Late-Night Code Optimization & Espresso",
        "theme": "coding",
        "prompt": (
            "A cozy yet modern creator desk setup deep in a late-night debugging "
            "session. A steaming espresso cup sitting on a dark desk next to a glowing "
            "mechanical keyboard. The monitor displays thousands of lines of C++ code, "
            "a side terminal window running automated tests, and a tranquil cyan "
            "particle sphere in standby mode. Moody workspace, atmospheric warm desk "
            "lamps contrasting cool blue screen light, soft bokeh effects."
        ),
    },
    {
        "id": 21,
        "title": "Autonomous Drone Fleet Command",
        "theme": "robotics",
        "prompt": (
            "An AI assistant managing telemetry and navigation vectors for an "
            "autonomous drone array. 3D topographic terrain map overlaid with real-time "
            "flight paths, altitude indicators, and battery status cards. A central "
            "blue orb coordinate hub synchronizes data feeds across six distinct drone "
            "camera streams. Tactical command center, dark mode GIS interface, neon "
            "vector graphics, ultra-detailed UI."
        ),
    },
    {
        "id": 22,
        "title": "High-Density Data Center Integration",
        "theme": "infrastructure",
        "prompt": (
            "A server rack cabinet with glowing blue status indicators, linked "
            "directly to an AI terminal. Optical fiber cables pulsing with light "
            "connected to high-density server blades. A nearby workstation monitor "
            "displays a blue particle sphere representing the system core, showing CPU "
            "load and GPU memory distribution. Industrial tech server room, sleek "
            "metallic surfaces, cinematic lens flare, high-tech infrastructure vibe."
        ),
    },
    {
        "id": 23,
        "title": "Holographic Molecular Docking Simulation",
        "theme": "biotech",
        "prompt": (
            "An AI model predicting molecular interactions for drug discovery research. "
            "Complex 3D protein structures docking with chemical compounds, rendered in "
            "glowing cyan and violet lattices. Quantitative binding energy metrics hover "
            "around the central reaction zone next to an active AI status monitor. "
            "Bio-tech research aesthetic, hyper-detailed molecular graphics, deep dark "
            "background, crisp lighting."
        ),
    },
    {
        "id": 24,
        "title": "Real-Time Multilingual Translation Pipeline",
        "theme": "ai",
        "prompt": (
            "An AI system processing and translating live multi-party spoken audio "
            "feeds. Dynamic sound wave tracks flowing into a central data funnel. "
            "Output text streams split into multiple foreign language script panels, "
            "with confidence scores and sentiment analysis bars updating in real time. "
            "Modern linguistics interface, clean typography, vibrant color-coded audio "
            "meters, minimalist dark theme."
        ),
    },
    {
        "id": 25,
        "title": "The Autonomous Git Repository Manager",
        "theme": "coding",
        "prompt": (
            "An AI agent executing automated code commits, pull requests, and merge "
            "conflict resolutions. A 3D git branch tree visualizer branching and "
            "merging with glowing green node points. Side logs display automated "
            "message prompts like Resolved Memory Leak in Core Loop and Optimized "
            "Shader Compilation. Software architecture visualization, dark IDE "
            "aesthetic, neon green and cyan accents, crisp vector lines."
        ),
    },
    {
        "id": 26,
        "title": "Solar Panel Micro-Grid Optimization",
        "theme": "energy",
        "prompt": (
            "An AI system balancing real-time energy production and distribution "
            "across a smart micro-grid. Isometric schematic of a modern off-grid house "
            "and workshop, showing live energy flow vectors from solar arrays and "
            "battery banks. Floating HUD elements monitor wattage, voltage spikes, and "
            "stored reserve capacity. Clean energy tech, architectural blueprint "
            "aesthetic, vibrant green and blue flow lines, modern render."
        ),
    },
    {
        "id": 27,
        "title": "The Edge Computing AI Micro-Node",
        "theme": "hardware",
        "prompt": (
            "A compact single-board computer running a localized AI assistant core. "
            "A tiny OLED screen attached to the circuit board displaying a mini glowing "
            "blue particle orb. Exposed copper heatsinks, GPIO pin connections, and "
            "braided cables arranged neatly on a dark anti-static mat. DIY hardware "
            "electronics lab, macro photography, shallow depth of field, sharp "
            "hardware details."
        ),
    },
    {
        "id": 28,
        "title": "Generative AI Video Rendering Node",
        "theme": "media",
        "prompt": (
            "An AI workstation compiling and processing multi-frame neural video render "
            "pipelines. A timeline editor with stacked neural network latent layers, "
            "attention map visualizations, and frame-by-frame tensor buffers. A glowing "
            "blue orb interface monitors GPU VRAM usage and frame-per-second generation "
            "rates. Next-gen media production suite, high contrast dark theme, vibrant "
            "neon accents, ultra-detailed UI."
        ),
    },
    {
        "id": 29,
        "title": "Structural Thermal Analysis Engine",
        "theme": "engineering",
        "prompt": (
            "An AI running thermal stress simulations on a high-performance aerospace "
            "heat exchanger. 3D turbine or exhaust geometry highlighted with gradient "
            "heatmaps ranging from deep blue to brilliant orange-red. Computational "
            "fluid dynamics vector streams loop through internal channels. Aerospace "
            "engineering suite, high-tech simulation lab, sharp gradient maps, "
            "photorealistic render."
        ),
    },
    {
        "id": 30,
        "title": "The Automated PCB Circuit Router",
        "theme": "hardware",
        "prompt": (
            "An AI agent laying out complex circuit board traces autonomously on screen. "
            "Dense multi-layer PCB design view with glowing green, gold, and red trace "
            "routes automatically drawing themselves around IC chips, microcontrollers, "
            "and SMD capacitors in real time. Electronic design automation software, "
            "high contrast, precise CAD line work, modern tech aesthetic."
        ),
    },
    {
        "id": 31,
        "title": "Autonomous Satellite Telemetry Monitor",
        "theme": "space",
        "prompt": (
            "An AI monitoring orbital mechanics and telemetry data for a satellite "
            "array. A glowing 3D Earth globe surrounded by orbital inclination rings "
            "and satellite node markers. Live telemetry feeds show signal strength "
            "graphs, orbital velocity numbers, and automated trajectory correction logs. "
            "Space agency command UI, dark cosmic backdrop, brilliant cyan and amber "
            "lighting, crisp vector graphics."
        ),
    },
    {
        "id": 32,
        "title": "The Deep Reinforcement Learning Playground",
        "theme": "ai",
        "prompt": (
            "An AI agent training inside a simulated physics environment to learn "
            "robotic arm manipulation. A 3D virtual environment on screen showing a "
            "robotic arm attempting object placement tasks. Overlaid graphs display "
            "reward curves, loss metrics, and training epoch counters rising steadily. "
            "Robotics research lab, modern simulation software UI, vibrant line charts, "
            "clean high-tech look."
        ),
    },
    {
        "id": 33,
        "title": "Automated Audio Mastering & DSP Hub",
        "theme": "audio",
        "prompt": (
            "An AI assistant applying digital signal processing and dynamic mastering "
            "to a film soundtrack. Multi-band parametric EQ curves shifting "
            "automatically, dynamic range compressors adjusting, and spatial 3D audio "
            "panning meters glowing around a central blue orb UI node. High-end audio "
            "engineering studio, dark UI with glowing equalizer bands, clean macro shot."
        ),
    },
    {
        "id": 34,
        "title": "The Autonomous Scientific Literature Synthesizer",
        "theme": "research",
        "prompt": (
            "An AI building a massive citation knowledge graph from thousands of "
            "academic PDFs. Hundreds of floating paper titles and author nodes linking "
            "together with glowing laser lines into a vast, organized 3D web. Selected "
            "nodes highlight key findings, research gaps, and methodologies in callout "
            "cards. Academic data science, futuristic research interface, elegant "
            "typography, deep navy and cyan tones."
        ),
    },
    {
        "id": 35,
        "title": "High-Speed Algorithmic Logic Analyzer",
        "theme": "hardware",
        "prompt": (
            "A multi-channel digital logic analyzer captured mid-diagnostic on an "
            "embedded system bus. Parallel digital square waveforms streaming across "
            "screen channels in bright green and yellow. An AI side panel decodes SPI, "
            "I2C, and UART bus data protocols in real time, tagging timing errors. "
            "Hardware debugging lab, high-tech diagnostic display, razor-sharp line "
            "graphics, industrial feel."
        ),
    },
    {
        "id": 36,
        "title": "The Personal AI Health & Productivity Matrix",
        "theme": "productivity",
        "prompt": (
            "An integrated dashboard tracking daily cognitive focus, sleep metrics, "
            "and task completion. Sleek circular progress rings, circadian rhythm bar "
            "charts, and task priority lists surrounding a gentle, pulsing warm-blue "
            "orb assistant that suggests optimal work breaks. Personal productivity "
            "HUD, clean modern bio-hacking aesthetic, soft ambient lighting, "
            "ultra-scannable UI."
        ),
    },
    {
        "id": 37,
        "title": "Automated 3D Printing Farm Manager",
        "theme": "manufacturing",
        "prompt": (
            "An AI monitoring a bank of high-speed 3D printers producing custom "
            "mechanical prototypes. Monitor displaying thermal camera streams of active "
            "print beds, filament level meters, and layer-by-layer G-code execution "
            "progress. Automated alerts highlight completed prints and bed temperatures. "
            "Industrial prototyping workshop, dark ambient room lit by print bed LEDs, "
            "clean monitoring interface."
        ),
    },
    {
        "id": 38,
        "title": "The Neural Network Architecture Designer",
        "theme": "ai",
        "prompt": (
            "A machine learning engineer using an AI agent to design and prune neural "
            "network layers. Interactive 3D visualization of deep neural layers showing "
            "tensor shapes and parameter weights passing between nodes with glowing data "
            "pulses. Deep learning development studio, dark space UI, vibrant "
            "multi-colored data channels, high resolution."
        ),
    },
    {
        "id": 39,
        "title": "Autonomous Smart Home Climate & Energy Controller",
        "theme": "automation",
        "prompt": (
            "An AI managing thermal efficiency, HVAC zoning, and smart glass tinting "
            "for a modern home. Architectural floor plan render showing temperature "
            "zones, airflow vector animations, and power consumption graphs. The blue "
            "particle assistant sits docked above the main control dashboard. "
            "Architectural automation, sleek modern smart home interface, soft cyan "
            "and emerald tones, clean lighting."
        ),
    },
    {
        "id": 40,
        "title": "Robotic Teleoperation HUD",
        "theme": "robotics",
        "prompt": (
            "First-person operator view inside a haptic VR rig controlling a remote "
            "bipedal robot. Stereoscopic dual-lens camera feed with overlaid depth "
            "grids, joint torque meters, and balance center-of-mass indicators. An AI "
            "co-pilot assists with obstacle avoidance trajectories. Advanced robotics "
            "teleoperation, immersive HUD, military-grade rugged interface design, "
            "high contrast."
        ),
    },
    {
        "id": 41,
        "title": "Automated Code Vulnerability Scanner",
        "theme": "cybersecurity",
        "prompt": (
            "An AI security agent auditing a massive codebase for zero-day exploits "
            "and buffer overflows. Scrolling code windows where vulnerable functions "
            "are instantly highlighted in warning red, automatically rewritten into "
            "secure syntax highlighted in bright green, accompanied by security patch "
            "notes. Cyber security terminal, high-contrast dark theme, vivid red/green "
            "code diffs, crisp typography."
        ),
    },
    {
        "id": 42,
        "title": "The Autonomous Synthesizer Patch Designer",
        "theme": "audio",
        "prompt": (
            "An AI assistant designing complex modular synthesizer audio patches from "
            "natural language descriptions. Virtual Eurorack modular synth wall on "
            "screen with glowing patch cables routing automatically between oscillators, "
            "filters, and LFO modules according to the AI's real-time DSP routing "
            "logic. Music tech laboratory, dark synth-cave atmosphere, vibrant glowing "
            "patch cables, intricate knurled knobs."
        ),
    },
    {
        "id": 43,
        "title": "Spacecraft Environmental Life-Support System",
        "theme": "space",
        "prompt": (
            "An AI controlling life-support, oxygen scrubbing, and cabin pressurization "
            "on a spacecraft module. Schematic diagram of air scrubbers, CO2 scrubbers, "
            "and pressure seals with real-time percentage gauges, flow rate indicators, "
            "and automated red-to-green status toggles across the board. Sci-fi "
            "spacecraft HUD, mission control aesthetic, ultra-clean vector graphics, "
            "high-contrast dark UI."
        ),
    },
    {
        "id": 44,
        "title": "The Autonomous Optical Inspection System",
        "theme": "manufacturing",
        "prompt": (
            "Computer vision AI analyzing silicon wafers on a semiconductor "
            "manufacturing line. High-magnification camera view of microchip dies under "
            "violet UV lighting, with bright yellow bounding boxes pinpointing "
            "sub-micron microscopic defects and micro-fractures in real time. "
            "Semiconductor cleanroom tech, macro photography, high-tech quality control "
            "UI, neon callouts."
        ),
    },
    {
        "id": 45,
        "title": "Automated Micro-Fluidic Lab-on-a-Chip Controller",
        "theme": "biotech",
        "prompt": (
            "AI assistant managing precise liquid handling across a microscopic "
            "lab-on-a-chip manifold. Microscopic view of tiny fluid channels with "
            "fluorescent dyes pulsing through channels, controlled by automated "
            "micro-valves. Flow rate graphs and mixing ratio meters line the screen "
            "borders. Bio-engineering lab, fluorescent neon visuals, crisp scientific "
            "interface, ultra-detailed micro shot."
        ),
    },
    {
        "id": 46,
        "title": "The Autonomous Firmware Flasher & Tester",
        "theme": "hardware",
        "prompt": (
            "A hardware test jig flashing custom compiled firmware onto multiple "
            "microcontroller boards in parallel. Multiple USB test rigs with flashing "
            "status LEDs connected to a main monitor displaying parallel terminal "
            "output windows, logic levels, and green SUCCESS: BOOTLOADER VERIFIED "
            "cards. Hardware QA lab, dark bench setting, glowing LED indicators, sharp "
            "industrial workstation aesthetic."
        ),
    },
    {
        "id": 47,
        "title": "Quantum Magnetic Levitation Control",
        "theme": "quantum",
        "prompt": (
            "An AI system fine-tuning magnetic field frequencies to stabilize a "
            "superconductor disk. 3D magnetic field flux lines rendered around a "
            "levitating disk, shifting dynamically as real-time feedback loops adjust "
            "coil voltages. Cryogenic temperature gauges hover nearby at 77 Kelvin. "
            "Experimental physics lab, glowing field line physics, dark sci-fi "
            "aesthetic, photorealistic detail."
        ),
    },
    {
        "id": 48,
        "title": "The Autonomous Subsea ROV Navigator",
        "theme": "exploration",
        "prompt": (
            "Deep-sea underwater remote operated vehicle interface guided by an AI "
            "sonar map. 3D multibeam sonar terrain map of the seafloor in neon green, "
            "flanked by camera feeds showing deep ocean trench structures, thruster "
            "vector angles, and depth gauges reading 3000 meters. Deep-ocean "
            "exploration HUD, dark abyss atmosphere, bright sonar vector displays, "
            "rugged UI layout."
        ),
    },
    {
        "id": 49,
        "title": "Automated Wind Tunnel Aerodynamic Profiler",
        "theme": "engineering",
        "prompt": (
            "AI analyzing smoke stream turbulence and drag coefficients over a "
            "high-performance vehicle chassis. 3D car body model in a virtual wind "
            "tunnel with colored streamline velocity vectors flowing over the surface. "
            "Real-time drag coefficient calculations and downforce distribution meters "
            "updating continuously. Automotive engineering center, sleek aerodynamic "
            "simulation visuals, vibrant flow streams, clean render."
        ),
    },
    {
        "id": 50,
        "title": "The Master Command Center Core",
        "theme": "command",
        "prompt": (
            "A complete multi-monitor master workstation running a fully integrated "
            "AI operating system. A central curved display featuring a massive glowing "
            "cyan particle sphere orb. Surrounding monitors display active code "
            "compilers, CAD schematics, server cluster load meters, security camera "
            "feeds, and automated research summaries, all operating in perfect "
            "synchronization. The ultimate engineer command room, tech-hero aesthetic, "
            "deep blues and glowing cyan accents, cinematic atmosphere, "
            "hyper-detailed wide shot."
        ),
    },
]

# All unique theme tags, sorted.
THEMES: list[str] = sorted({p["theme"] for p in PROMPTS})
