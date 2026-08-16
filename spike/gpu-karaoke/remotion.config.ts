import {Config} from '@remotion/cli/config';

// WebGL in headless Chrome. If the render comes out black, switch to 'swangle'
// (software ANGLE) — slower but works on machines without a usable GPU driver.
Config.setChromiumOpenGlRenderer('angle');
Config.setVideoImageFormat('jpeg');
Config.setConcurrency(1);
