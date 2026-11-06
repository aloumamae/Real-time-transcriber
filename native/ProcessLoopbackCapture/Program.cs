using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using NAudio.CoreAudioApi;
using NAudio.CoreAudioApi.Interfaces;
using NAudio.Wave;
using NAudio.Wasapi.CoreAudioApi.Interfaces;

internal static class Program
{
    private const string ProcessLoopbackDevice = "VAD\\Process_Loopback";
    private const int S_OK = 0;

    private static int Main(string[] args)
    {
        try
        {
            var options = ParseArgs(args);
            if (options.Pid <= 0)
            {
                Console.Error.WriteLine("Invalid PID.");
                return 2;
            }

            using var audioClient = ActivateProcessLoopbackClient(
                options.Pid,
                includeTargetTree: true
            );

            var waveFormat = new WaveFormat(options.SampleRate, 16, 1);
            audioClient.Initialize(
                AudioClientShareMode.Shared,
                AudioClientStreamFlags.Loopback | AudioClientStreamFlags.AutoConvertPcm | AudioClientStreamFlags.SrcDefaultQuality,
                0,
                0,
                waveFormat,
                Guid.Empty
            );

            using var captureClient = audioClient.AudioCaptureClient;
            using var stdout = Console.OpenStandardOutput();
            var buffer = new byte[Math.Max(4096, waveFormat.AverageBytesPerSecond / 10)];

            audioClient.Start();
            while (true)
            {
                var packetSize = captureClient.GetNextPacketSize();
                while (packetSize > 0)
                {
                    var data = captureClient.GetBuffer(out var frames, out var flags);
                    var bytesToWrite = frames * waveFormat.BlockAlign;
                    if (bytesToWrite > 0)
                    {
                        if ((flags & AudioClientBufferFlags.Silent) != 0)
                        {
                            WriteSilence(stdout, buffer, bytesToWrite);
                        }
                        else
                        {
                            if (buffer.Length < bytesToWrite)
                            {
                                buffer = new byte[bytesToWrite];
                            }
                            Marshal.Copy(data, buffer, 0, bytesToWrite);
                            stdout.Write(buffer, 0, bytesToWrite);
                        }
                    }
                    captureClient.ReleaseBuffer(frames);
                    packetSize = captureClient.GetNextPacketSize();
                }

                stdout.Flush();
                Thread.Sleep(2);
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.ToString());
            return 1;
        }
    }

    private static void WriteSilence(Stream stream, byte[] scratch, int totalBytes)
    {
        Array.Clear(scratch, 0, Math.Min(scratch.Length, totalBytes));
        var remaining = totalBytes;
        while (remaining > 0)
        {
            var n = Math.Min(remaining, scratch.Length);
            stream.Write(scratch, 0, n);
            remaining -= n;
        }
    }

    private static (int Pid, int SampleRate) ParseArgs(string[] args)
    {
        int pid = 0;
        string exeName = "";
        int sampleRate = 48000;

        for (int i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--pid":
                    if (i + 1 < args.Length && int.TryParse(args[i + 1], out var p))
                    {
                        pid = p;
                        i++;
                    }
                    break;
                case "--exe":
                    if (i + 1 < args.Length)
                    {
                        exeName = args[i + 1];
                        i++;
                    }
                    break;
                case "--rate":
                    if (i + 1 < args.Length && int.TryParse(args[i + 1], out var sr) && sr > 0)
                    {
                        sampleRate = sr;
                        i++;
                    }
                    break;
            }
        }

        if (pid <= 0 && !string.IsNullOrWhiteSpace(exeName))
        {
            pid = ResolvePidByExe(exeName, sampleRate);
        }

        return (pid, sampleRate);
    }


    private static int ResolvePidByExe(string exeName, int sampleRate)
    {
        var name = Path.GetFileNameWithoutExtension(exeName).ToLowerInvariant();
        var candidates = Process.GetProcessesByName(name)
            .Where(p =>
            {
                try { return !p.HasExited; } catch { return false; }
            })
            .ToArray();
        if (candidates.Length == 0)
        {
            throw new InvalidOperationException($"Process not found for executable: {exeName}");
        }

        Process? bestByActivity = null;
        double bestEnergy = 0;
        foreach (var candidate in candidates)
        {
            var energy = MeasureProcessEnergy(candidate.Id, sampleRate, 350);
            if (energy > bestEnergy)
            {
                bestEnergy = energy;
                bestByActivity = candidate;
            }
        }

        if (bestByActivity != null && bestEnergy > 0)
        {
            return bestByActivity.Id;
        }

        // Fallback if no activity detected in the probe window.
        var process = candidates
            .OrderByDescending(p => !string.IsNullOrWhiteSpace(p.MainWindowTitle))
            .ThenByDescending(p => p.Id)
            .First();
        return process.Id;
    }

    private static double MeasureProcessEnergy(int pid, int sampleRate, int probeMs)
    {
        try
        {
            using var audioClient = ActivateProcessLoopbackClient(pid, includeTargetTree: true);
            var waveFormat = new WaveFormat(sampleRate, 16, 1);
            audioClient.Initialize(
                AudioClientShareMode.Shared,
                AudioClientStreamFlags.Loopback | AudioClientStreamFlags.AutoConvertPcm | AudioClientStreamFlags.SrcDefaultQuality,
                0,
                0,
                waveFormat,
                Guid.Empty
            );
            using var captureClient = audioClient.AudioCaptureClient;
            audioClient.Start();
            var started = Stopwatch.StartNew();
            double energy = 0;
            var temp = new byte[Math.Max(4096, waveFormat.AverageBytesPerSecond / 10)];

            while (started.ElapsedMilliseconds < probeMs)
            {
                var packetSize = captureClient.GetNextPacketSize();
                while (packetSize > 0)
                {
                    var data = captureClient.GetBuffer(out var frames, out var flags);
                    var bytesToRead = frames * waveFormat.BlockAlign;
                    if ((flags & AudioClientBufferFlags.Silent) == 0 && bytesToRead > 0)
                    {
                        if (temp.Length < bytesToRead)
                        {
                            temp = new byte[bytesToRead];
                        }
                        Marshal.Copy(data, temp, 0, bytesToRead);
                        for (int i = 0; i + 1 < bytesToRead; i += 2)
                        {
                            short s = (short)(temp[i] | (temp[i + 1] << 8));
                            energy += Math.Abs(s);
                        }
                    }
                    captureClient.ReleaseBuffer(frames);
                    packetSize = captureClient.GetNextPacketSize();
                }
                Thread.Sleep(2);
            }

            audioClient.Stop();
            return energy;
        }
        catch
        {
            return 0;
        }
    }

    private static AudioClient ActivateProcessLoopbackClient(int pid, bool includeTargetTree)
    {
        var asm = typeof(AudioClient).Assembly;
        var nativeMethodsType = asm.GetType("NAudio.Wasapi.CoreAudioApi.NativeMethods", throwOnError: true)!;
        var activationParamsType = asm.GetType("NAudio.CoreAudioApi.AudioClientActivationParams", throwOnError: true)!;
        var processParamsType = asm.GetType("NAudio.CoreAudioApi.AudioClientProcessLoopbackParams", throwOnError: true)!;
        var activationTypeEnum = asm.GetType("NAudio.CoreAudioApi.AudioClientActivationType", throwOnError: true)!;
        var loopbackModeEnum = asm.GetType("NAudio.CoreAudioApi.ProcessLoopbackMode", throwOnError: true)!;

        var processParams = Activator.CreateInstance(processParamsType)!;
        processParamsType.GetField("TargetProcessId")!.SetValue(processParams, (uint)pid);
        processParamsType.GetField("ProcessLoopbackMode")!.SetValue(
            processParams,
            Enum.Parse(loopbackModeEnum, includeTargetTree ? "IncludeTargetProcessTree" : "ExcludeTargetProcessTree")
        );

        var activationParams = Activator.CreateInstance(activationParamsType)!;
        activationParamsType.GetField("ActivationType")!.SetValue(
            activationParams,
            Enum.Parse(activationTypeEnum, "ProcessLoopback")
        );
        activationParamsType.GetField("ProcessLoopbackParams")!.SetValue(activationParams, processParams);

        var activationParamsSize = Marshal.SizeOf(activationParamsType);
        var activationParamsPtr = Marshal.AllocHGlobal(activationParamsSize);
        var propVariantPtr = IntPtr.Zero;
        var blobDataPtr = IntPtr.Zero;
        try
        {
            Marshal.StructureToPtr(activationParams, activationParamsPtr, false);

            blobDataPtr = activationParamsPtr;
            var pv = new PropVariantBlob(blobDataPtr, activationParamsSize);
            propVariantPtr = Marshal.AllocHGlobal(Marshal.SizeOf<PropVariantBlob>());
            Marshal.StructureToPtr(pv, propVariantPtr, false);

            var tcs = new TaskCompletionSource<IAudioClient>(TaskCreationOptions.RunContinuationsAsynchronously);
            var handler = new ActivationCompletionHandler(tcs);
            var activateMethod = nativeMethodsType.GetMethod(
                "ActivateAudioInterfaceAsync",
                BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic
            )!;

            object? asyncOperation = null;
            var parameters = new object?[]
            {
                ProcessLoopbackDevice,
                typeof(IAudioClient).GUID,
                propVariantPtr,
                handler,
                asyncOperation
            };
            activateMethod.Invoke(null, parameters);

            var client = tcs.Task.Wait(TimeSpan.FromSeconds(10))
                ? tcs.Task.Result
                : throw new TimeoutException("Timed out activating process loopback client.");

            return new AudioClient(client);
        }
        finally
        {
            if (propVariantPtr != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(propVariantPtr);
            }
            if (activationParamsPtr != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(activationParamsPtr);
            }
        }
    }

    private sealed class ActivationCompletionHandler : IActivateAudioInterfaceCompletionHandler
    {
        private readonly TaskCompletionSource<IAudioClient> _tcs;

        public ActivationCompletionHandler(TaskCompletionSource<IAudioClient> tcs)
        {
            _tcs = tcs;
        }

        public void ActivateCompleted(IActivateAudioInterfaceAsyncOperation operation)
        {
            try
            {
                operation.GetActivateResult(out var hr, out var obj);
                if (hr != S_OK)
                {
                    _tcs.TrySetException(new COMException($"ActivateAudioInterfaceAsync failed with HRESULT 0x{hr:X8}", hr));
                    return;
                }

                if (obj is IAudioClient client)
                {
                    _tcs.TrySetResult(client);
                    return;
                }

                _tcs.TrySetException(new InvalidCastException("Activation result is not IAudioClient."));
            }
            catch (Exception ex)
            {
                _tcs.TrySetException(ex);
            }
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Blob
    {
        public int Length;
        public IntPtr Data;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PropVariantBlob
    {
        public ushort vt;
        public ushort wReserved1;
        public ushort wReserved2;
        public ushort wReserved3;
        public Blob blob;

        public PropVariantBlob(IntPtr data, int size)
        {
            vt = (ushort)VarEnum.VT_BLOB;
            wReserved1 = 0;
            wReserved2 = 0;
            wReserved3 = 0;
            blob = new Blob
            {
                Data = data,
                Length = size
            };
        }
    }
}
