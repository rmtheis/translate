/*
 * Copyright (C) 2012 Mikel Artetxe
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License as
 * published by the Free Software Foundation; either version 2 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA
 * 02111-1307, USA.
 */
package com.qvyshift.translate;

import android.util.Log;

import java.io.File;
import java.io.FilenameFilter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;

public class ApertiumInstallation {
  /** Mode title ("English → Spanish") → mode id ("en-es"). Read-only for callers. */
  public final HashMap<String, String> titleToMode = new HashMap<>();
  /** Mode id ("en-es") → pair package dir ("apertium-eng-spa"). Read-only for callers. */
  public final HashMap<String, String> modeToPackage = new HashMap<>();

  /** Observers fired on the UI thread after a rescan. */
  public final ArrayList<Runnable> observers = new ArrayList<>();

  private final File packagesDir;

  ApertiumInstallation(File packagesDir) {
    this.packagesDir = packagesDir;
    packagesDir.mkdirs();
  }

  private static final FilenameFilter PAIR_DIR = (dir, name) ->
      name.matches("apertium-[a-z][a-z][a-z]?-[a-z][a-z][a-z]?");
  private static final FilenameFilter MODE_FILE = (dir, name) -> name.endsWith(".mode");

  private void notifyObservers() {
    for (Runnable r : observers) App.handler.post(r);
  }

  public void rescanForPackages() {
    titleToMode.clear();
    modeToPackage.clear();

    String[] installedPackages = packagesDir.list(PAIR_DIR);
    if (installedPackages == null) installedPackages = new String[0];
    Log.d("ApertiumInstallation", "Scanning " + packagesDir + " found " + Arrays.asList(installedPackages));

    for (String pkg : installedPackages) {
      File pkgDir = new File(packagesDir, pkg);
      for (String modeId : findModeIds(pkgDir)) {
        String title = LanguageTitles.getTitle(modeId);
        titleToMode.put(title, modeId);
        modeToPackage.put(modeId, pkg);
        Log.d("ApertiumInstallation", modeId + " / " + title + " (" + pkg + ")");
      }
    }
    notifyObservers();
  }

  /**
   * Walk a pair's install dir for {@code *.mode} files. The mode-file location varies with
   * how the pair was packaged: old JAR-style installs put them under {@code data/modes/};
   * Debian-format installs put them at the pair root. Stop at the first directory that
   * contains any mode files.
   */
  private static ArrayList<String> findModeIds(File pkgDir) {
    ArrayList<String> ids = new ArrayList<>();
    for (String sub : new String[]{"data/modes", "modes", ""}) {
      File dir = sub.isEmpty() ? pkgDir : new File(pkgDir, sub);
      String[] files = dir.list(MODE_FILE);
      if (files == null || files.length == 0) continue;
      for (String f : files) {
        ids.add(f.substring(0, f.length() - ".mode".length()));
      }
      return ids;
    }
    return ids;
  }

  public void installJar(File tmpJarFile, String pkg) throws IOException {
    File dir = new File(packagesDir, pkg);
    FileUtils.unzip(tmpJarFile.getPath(), dir.getPath(), (d, filename) -> !filename.endsWith(".class"));
    dir.setLastModified(tmpJarFile.lastModified());
    // Legacy JARs include a classes.dex for the Java-port transfer classes; we run native
    // binaries now so it's dead weight. Delete if present.
    new File(dir, "classes.dex").delete();
  }

  public void uninstallPackage(String pkg) {
    FileUtils.remove(new File(packagesDir, pkg));
  }

  public String getBasedirForPackage(String pkg) {
    return packagesDir + "/" + pkg;
  }
}
