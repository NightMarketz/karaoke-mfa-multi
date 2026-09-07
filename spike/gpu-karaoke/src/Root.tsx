import {Composition} from 'remotion';
import {KaraokeGpu} from './KaraokeGpu';
import {KaraokeSong} from './KaraokeSong';
import data from './spike_data.json';
import song from './song_data.json';

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="KaraokeGpu"
        component={KaraokeGpu}
        durationInFrames={data.durationInFrames}
        fps={data.fps}
        width={data.width}
        height={data.height}
      />
      <Composition
        id="KaraokeSong"
        component={KaraokeSong}
        durationInFrames={song.durationInFrames}
        fps={song.fps}
        width={song.width}
        height={song.height}
      />
    </>
  );
};
